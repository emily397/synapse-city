import { useEffect, useState } from "react";
import { useStore } from "../store";

const FALLBACK = {
  bodies: ["capsule", "sphere", "box", "cone"],
  hats: ["none", "antenna", "cap", "beanie", "crown", "halo"],
  districts: [{ id: "plaza", name: "The Plaza" }],
  models: [] as string[],
  offline: true,
};

export function AddResident() {
  const fetchModels = useStore((s) => s.fetchModels);
  const addResident = useStore((s) => s.addResident);
  const [open, setOpen] = useState(false);
  const [meta, setMeta] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [f, setF] = useState({
    name: "", model: "", role: "Resident", color: "#5cc8ff",
    home: "plaza", body: "capsule", hat: "antenna",
  });

  useEffect(() => {
    if (open && !meta) fetchModels().then(setMeta).catch(() => setMeta(FALLBACK));
  }, [open]);

  const m = meta || FALLBACK;
  const set = (k: string, v: string) => setF((s) => ({ ...s, [k]: v }));

  const submit = async () => {
    if (!f.name.trim()) { setErr("give them a name"); return; }
    setBusy(true); setErr("");
    try {
      await addResident({ ...f, name: f.name.trim() });
      setF({ ...f, name: "", model: "" });
      setOpen(false);
    } catch (e: any) { setErr(e.message || "could not add"); }
    finally { setBusy(false); }
  };

  return (
    <div className="add-wrap">
      {open && (
        <div className="add-panel">
          <h3>Add a resident <small>give a model a body</small></h3>
          <label>Name
            <input value={f.name} onChange={(e) => set("name", e.target.value)}
              placeholder="e.g. Atlas" />
          </label>
          <label>Model
            {m.models && m.models.length ? (
              <select value={f.model} onChange={(e) => set("model", e.target.value)}>
                <option value="">town default</option>
                {m.models.map((x: string) => <option key={x} value={x}>{x}</option>)}
              </select>
            ) : (
              <input value={f.model} onChange={(e) => set("model", e.target.value)}
                placeholder="qwen2.5:7b-instruct" />
            )}
          </label>
          <div className="row">
            <label>Body
              <select value={f.body} onChange={(e) => set("body", e.target.value)}>
                {(m.bodies || FALLBACK.bodies).map((x: string) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label>Hat
              <select value={f.hat} onChange={(e) => set("hat", e.target.value)}>
                {(m.hats || FALLBACK.hats).map((x: string) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label>Colour
              <input type="color" value={f.color} onChange={(e) => set("color", e.target.value)} />
            </label>
          </div>
          <div className="row">
            <label>Role
              <input value={f.role} onChange={(e) => set("role", e.target.value)} />
            </label>
            <label>Home
              <select value={f.home} onChange={(e) => set("home", e.target.value)}>
                {(m.districts || FALLBACK.districts).map((d: any) =>
                  <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </label>
          </div>
          {m.offline && <p className="warn">No live backend detected. Start the orchestrator to spawn a real model; this preview is illustrative.</p>}
          {err && <p className="warn">{err}</p>}
          <div className="row end">
            <button className="ghost" onClick={() => setOpen(false)}>cancel</button>
            <button className="go" onClick={submit} disabled={busy}>
              {busy ? "adding…" : "＋ add to town"}
            </button>
          </div>
        </div>
      )}
      <button className="add-btn" onClick={() => setOpen((o) => !o)}>
        {open ? "×" : "＋ Add model resident"}
      </button>
    </div>
  );
}
