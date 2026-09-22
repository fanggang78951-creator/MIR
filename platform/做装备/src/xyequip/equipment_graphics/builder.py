"""Build action and static candidates from manifest sources."""
from __future__ import annotations
import hashlib
import uuid
from pathlib import Path
from .action_wil import build_action_wil_wix
from .static_wzl import build_static_pair

def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def build_prepared_files(manifest: dict, preflight: dict) -> list[dict]:
    source_hashes=preflight.get("sourceHashes", {})
    target_hashes=preflight.get("targetHashes", {})
    def baseline(path: Path) -> str | None:
        key=str(path.resolve())
        if key not in target_hashes: raise ValueError(f"preflight缺少目标哈希: {path}")
        return target_hashes[key]
    out = Path(manifest["outputRoot"]) / "prepared" / uuid.uuid4().hex; out.mkdir(parents=True, exist_ok=False)
    target = manifest["target"]; client = Path(target["clientData"])
    prepared=[]; updates={u["idx"]:u for u in preflight.get("shapeUpdates",[])}
    static_groups={}
    for item, resolved in zip(manifest["items"], preflight["resolvedItems"]):
        sources=item["sources"]; action=item["action"]; kind=item["kind"]
        update=updates.get(resolved["idx"]); shape=update["newShape"] if update else resolved["shape"]
        library=action["library"]; stem=f"{library}_{shape}"
        wil=out/(stem+".wil"); wix=out/(stem+".wix")
        build_action_wil_wix(kind="weapon" if kind=="weapon" else "human",source_root=Path(sources["actionFrames"]),output_wil=wil,output_wix=wix,frame_count=int(manifest["encoding"]["actionFrameCount"]),source_filename_digits=int(action.get("sourceFrameDigits",6)),alpha_cutoff=int(manifest["encoding"]["alphaCutoff"]),treat_one_by_one_as_empty=bool(action.get("treatOneByOneAsEmpty",True)))
        for file in (wil,wix):
            # Graphics libraries use numeric names (Weapon/1402.wil), while
            # candidate filenames retain their library prefix for evidence.
            live=Path(target["graphicsRoots"][library]) / f"{shape}{file.suffix}"
            prepared.append({"candidate":str(file),"target":str(live),"candidateSha256":_sha(file),"targetSha256":baseline(live),"role":"client-action"})
        static=item["static"]
        for library in static.get("libraries",[]):
            image=sources["innerImage"] if library=="StateItem" else sources["bagImage"]
            place=static["innerPlacement"] if library=="StateItem" else static["bagPlacement"]
            static_groups.setdefault(library,[]).append({"index":resolved["looks"],"image":image,"placement":place,"alpha_cutoff":manifest["encoding"]["alphaCutoff"]})
    patch_root=Path(target["launcherPatchData"])
    for library,replacements in static_groups.items():
        wzl=client/(library+".wzl"); wzx=client/(library+".wzx"); ow,ox=out/(library+".wzl"),out/(library+".wzx")
        build_static_pair(wzl,wzx,replacements,ow,ox)
        for file,live,role in ((ow,wzl,"client-static"),(ox,wzx,"client-static"),(ow,patch_root/ow.name,"launcher-patch"),(ox,patch_root/ox.name,"launcher-patch")):
            prepared.append({"candidate":str(file),"target":str(live),"candidateSha256":_sha(file),"targetSha256":baseline(live),"role":role})
    for key,digest in source_hashes.items():
        if _sha(Path(key)) != digest: raise ValueError(f"来源构建期间漂移: {key}")
    for item in prepared:
        live=Path(item["target"])
        if live.exists() and _sha(live) != item["targetSha256"]: raise ValueError(f"目标构建期间漂移: {live}")
    expected = [dict(item, after=item["candidateSha256"]) for item in prepared]
    # Keep the complete verification inventory, but never schedule a bytewise
    # identical candidate for a second write.
    preflight["expectedFiles"] = expected
    return [item for item in prepared if item["targetSha256"] != item["candidateSha256"]]
