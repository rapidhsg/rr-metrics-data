"""Sales board engine: rates every upcoming appointment for every rep.

Two predictions per lead and rep, learned from the last `data_window_days` of sits (certified close rate rules):
  close    : chance the homeowner buys from this rep
  same_day : chance they sign at the first sit
Pick score = close + same_day_weight x same_day (the weight is worked out from data, see same_day_value()).

The model has a lead layer (source, area, time, speed to appointment, type, roof age, note signals, AI note tags, CSR)
and a rep layer (rep overall, new-rep start, and rep fit on lead type, area, source, time of day and note signals).
Everything is pulled toward the team average until the data proves it (shrinkage), so reps with few sits sit near
average and reps with many sits stand on their own record. Recent sits count more (half-life decay)."""
import json, re, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import sparse
from sklearn.linear_model import LogisticRegression

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "rules"))
import rr_metrics as rr  # certified loader and close rate rules

CFG = json.loads((HERE / "settings.json").read_text())
MEM = HERE / "memory"

def tuned():
    p = MEM / "tuned.json"
    t = dict(CFG["starting_tuning"])
    if p.exists(): t.update(json.loads(p.read_text()).get("current", {}))
    return t

# ---------------- data ----------------
def load(path):
    df = rr.load(path)
    raw = pd.read_csv(rr._repaired_csv(path), low_memory=False, usecols=["Initial Appointment Date"])["Initial Appointment Date"]
    df["appt_time"] = pd.to_datetime(raw, format="%m/%d/%y %I:%M %p", errors="coerce")
    df["guid"] = df["Job Number Url"].astype(str).str.extract(r"/jobs/([0-9a-f-]{36})")[0]
    return df

def note_tags():
    p = MEM / "note_tags.json"
    return json.loads(p.read_text()).get("tags", {}) if p.exists() else {}

def daypart(h):
    return "morning" if h < 12 else "midday" if h < 14 else "afternoon" if h < 17 else "evening"

def age_of(x):
    m = re.search(r"(\d{1,2})\s*(?:\+|-|to)?\s*(?:\d{1,2}\s*)?(?:yrs|years|yr|year)", x)
    return int(m.group(1)) if m else None

def features(df, tags=None):
    """Descriptive columns for any set of jobs (past sits or upcoming appointments)."""
    tags = tags if tags is not None else note_tags()
    x = pd.DataFrame(index=df.index)
    x["guid"] = df["guid"]
    x["date"] = df["Initial Appointment Date"]
    x["src"] = df["Parent Lead Source"].fillna("none").str.upper()
    x["sub"] = df["Sub Lead Source"].fillna("none").str.upper()
    z = df["Job: Location Zip Code"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str[:5]
    x["zip"], x["z3"] = z, z.str[:3]
    x["dp"] = df["appt_time"].dt.hour.fillna(12).map(daypart)
    x["dow"] = x["date"].dt.dayofweek.astype(str)
    l2a = (df["Initial Appointment Date"] - df["Lead Milestone Date"]).dt.days
    x["l2a"] = l2a
    x["speed"] = pd.cut(l2a, [-99, 0, 1, 2, 7, 14, 9999], labels=["same day", "next day", "2 days", "3-7 days", "8-14 days", "15+ days"]).astype(str)
    x["csr"] = df["Appointment Set By"].fillna("none")
    notes = df["INITIAL LEAD NOTES"] if "INITIAL LEAD NOTES" in df else pd.Series(np.nan, index=df.index)
    low = notes.fillna("").str.lower()
    x["has_notes"] = notes.notna()
    for k, p in CFG["note_signals"].items():
        x["s_" + k] = low.str.contains(p, regex=True)
    age = low.map(age_of)
    x["roofage"] = pd.cut(age, [0, 9, 15, 20, 99], labels=["under 10 yrs", "10-15 yrs", "15-20 yrs", "20+ yrs"]).astype(str).replace("nan", "unknown")
    REPAIR = r"repair|patch|fix|leak"
    REPLACE = r"replac|new roof|full roof|rip|re-?roof|tear ?off|redo the roof|whole roof|entire roof"
    rp = low.str.contains(REPAIR) & ~low.str.contains(REPLACE)
    wt = df["Work Type"].fillna("")
    x["ltype"] = np.select([low.str.contains(REPLACE), rp, wt.eq("New"), wt.eq("Repair")], ["replace", "repair", "replace", "repair"], "other")
    x["comm"] = df["Job Category"].eq("Commercial")
    x["spec"] = x["s_specialty"] | df["Job Trade Type"].fillna("").str.contains("Signature Roofing")
    # AI note tags (written by the Claude note reader into memory/note_tags.json)
    x["ai"] = x["guid"].map(lambda g: tags.get(g, []) if isinstance(g, str) else [])
    x["rep"] = df["Primary Salesperson"].fillna("none")
    return x

def rep_experience(df):
    """Sits each rep had run before each sit (all history, certified sit rules)."""
    m = rr.masks(df, "2000-01-01", "2100-01-01")["close_sits_company"]
    s = df.loc[m, ["Primary Salesperson", "Initial Appointment Date"]].sort_values("Initial Appointment Date")
    return s, s.groupby("Primary Salesperson").cumcount()

# ---------------- model ----------------
SCALE = dict(src=1.0, sub=0.5, z3=0.6, zip=0.3, dp=0.6, dow=0.4, speed=0.8, csr=0.5, ltype=0.9, roofage=0.6,
             sig=0.6, ai=0.6, rep=0.8, newrep=1.0, rep_x=0.35)
LABEL = dict(src="Lead source", sub="Sub source", z3="Area", zip="Zip", dp="Time of day", dow="Weekday", speed="Speed to appointment",
             csr="Set by", ltype="Lead type", roofage="Roof age", rep="Rep", repx_ltype="Rep fit: lead type", repx_z3="Rep fit: area",
             repx_src="Rep fit: source", repx_dp="Rep fit: time of day")

class Model:
    def __init__(self, C, half_life, bands):
        self.C, self.hl, self.bands = C, half_life, bands

    def _design(self, x, fit=False):
        blocks, cols = [], []
        def onehot(name, s, scale, minn=1):
            if fit:
                vc = s.value_counts()
                self.levels[name] = [v for v in vc.index if vc[v] >= minn]
            lv = self.levels[name]; idx = {v: i for i, v in enumerate(lv)}
            c = s.map(idx); m = c.notna().values; r = np.arange(len(s))
            blocks.append(sparse.csr_matrix((np.full(m.sum(), scale), (r[m], c[m].astype(int).values)), shape=(len(s), len(lv))))
            cols.extend(f"{name}={v}" for v in lv)
        onehot("src", x.src, SCALE["src"], 10); onehot("sub", x["sub"], SCALE["sub"], 15)
        onehot("z3", x.z3, SCALE["z3"], 10); onehot("zip", x.zip, SCALE["zip"], 8)
        onehot("dp", x.dp, SCALE["dp"]); onehot("dow", x.dow, SCALE["dow"]); onehot("speed", x.speed, SCALE["speed"])
        onehot("csr", x.csr, SCALE["csr"], 15); onehot("ltype", x.ltype, SCALE["ltype"]); onehot("roofage", x.roofage, SCALE["roofage"])
        sig = [c for c in x.columns if c.startswith("s_")] + ["has_notes", "comm"]
        blocks.append(sparse.csr_matrix(x[sig].astype(float).values * SCALE["sig"])); cols.extend(sig)
        # AI tags: any tag seen on 15+ training sits becomes an input
        if fit:
            vc = pd.Series([t for ts in x.ai for t in ts]).value_counts()
            self.ai_tags = [t for t in vc.index if vc[t] >= 15]
        A = np.array([[t in ts for t in self.ai_tags] for ts in x.ai], dtype=float).reshape(len(x), len(self.ai_tags))
        blocks.append(sparse.csr_matrix(A * SCALE["ai"])); cols.extend("ai_" + t for t in self.ai_tags)
        onehot("rep", x.rep, SCALE["rep"])
        b0, b1 = self.bands
        blocks.append(sparse.csr_matrix(np.c_[x.rep_n.lt(b0), x.rep_n.between(b0, b1 - 1)].astype(float) * SCALE["newrep"]))
        cols += [f"newrep_first{b0}", f"newrep_{b0}to{b1}"]
        for g in ["ltype", "z3", "src", "dp"]:
            onehot("repx_" + g, x.rep + "|" + x[g].astype(str), SCALE["rep_x"], 6)
        for k in ["leak", "referral", "shopper", "budget", "firstcall", "noleak", "storm", "specialty"]:
            onehot("repx_s_" + k, x.rep.where(x["s_" + k]), SCALE["rep_x"], 6)
        self.cols = cols
        return sparse.hstack(blocks).tocsr()

    def fit(self, x, y, ref):
        self.ref, self.levels = pd.Timestamp(ref), {}
        X = self._design(x, fit=True)
        w = 0.5 ** ((self.ref - x.date).dt.days.clip(lower=0) / self.hl)
        self.m = LogisticRegression(C=self.C, max_iter=5000).fit(X, y, sample_weight=w.values)
        return self

    def predict(self, x):
        return self.m.predict_proba(self._design(x))[:, 1]

    def reasons(self, x, n=3):
        """Top pushes up and down for each row, in plain words."""
        X = self._design(x); co = self.m.coef_[0]; out = []
        for i in range(X.shape[0]):
            row = X.getrow(i); contrib = {}
            for j, v in zip(row.indices, row.data):
                name = self.cols[j]; g = name.split("=")[0]
                if g.startswith("repx_s_"): label = "Rep fit on '" + g[7:] + "' notes"
                elif g in LABEL: label = LABEL[g] + (": " + name.split("=", 1)[1].split("|")[-1] if "=" in name and g != "rep" else "")
                elif name.startswith("s_"): label = "Note: " + name[2:]
                elif name.startswith("ai_"): label = "AI note tag: " + name[3:]
                elif name.startswith("newrep"): label = "Newer rep (still proving out)"
                else: label = name
                contrib[label] = contrib.get(label, 0) + co[j] * v
            s = pd.Series(contrib).sort_values()
            out.append(dict(up=[[k, round(v, 3)] for k, v in s[s > 0.02].tail(n)[::-1].items()],
                            down=[[k, round(v, 3)] for k, v in s[s < -0.02].head(n).items()]))
        return out

# ---------------- training sets ----------------
def training(df, today, x_all=None):
    today = pd.Timestamp(today).normalize()
    win0 = today - pd.Timedelta(days=CFG["data_window_days"])
    m = rr.masks(df, win0, today)["close_sits_company"]
    S = df[m]
    x = features(S)
    hist, n = rep_experience(df)
    x["rep_n"] = n.reindex(x.index).fillna(0)
    ap = S["Approved Milestone Date"]
    x["y_close"] = ap.notna().astype(int)
    x["y_same"] = (ap.notna() & ((ap - S["Initial Appointment Date"]).dt.days <= 0)).astype(int)
    x["ok_close"] = S["Initial Appointment Date"] <= today - pd.Timedelta(days=CFG["close_label_wait_days"])
    x["ok_same"] = S["Initial Appointment Date"] <= today - pd.Timedelta(days=CFG["same_day_label_wait_days"])
    return S, x

def fit_both(x, today, t):
    c = x[x.ok_close]; s = x[x.ok_same]
    mc = Model(t["shrink_C"], t["half_life_days"], CFG["new_rep_bands"]).fit(c, c.y_close.values, today)
    ms = Model(t["shrink_C"], t["half_life_days"], CFG["new_rep_bands"]).fit(s, s.y_same.values, today)
    return mc, ms

def same_day_value(S):
    """What a same-day sale is worth vs a later sale: contract x profit % x (1 - cancel rate). Weight = ratio - 1."""
    sold = S[S["Approved Milestone Date"].notna()].copy()
    same = (sold["Approved Milestone Date"] - sold["Initial Appointment Date"]).dt.days <= 0
    def val(g):
        return g["Contract Amount"].mean() * g["Profit %"].clip(-1, 1).median() * (1 - g["Current Milestone"].eq("Dead").mean())
    a, b = val(sold[same]), val(sold[~same])
    return dict(same_day_value=round(a), later_value=round(b), weight=round(max(0.0, a / b - 1), 3),
                n_same=int(same.sum()), n_later=int((~same).sum()))
