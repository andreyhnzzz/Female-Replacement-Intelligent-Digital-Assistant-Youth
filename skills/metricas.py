"""SKILL 1 — metricas: jalar numeros.

Dos fuentes:
  1. Vitales de la maquina (CPU, RAM, disco, red, bateria).
  2. Metricas del vault: cualquier nota con `metric:` en el frontmatter,
     o lineas `- clave:: valor` (sintaxis Dataview, sin necesitar Dataview).
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from typing import Any

from .base import Skill, SkillContext, SkillResult

INLINE_METRIC = re.compile(r"^\s*[-*]?\s*([\wÁÉÍÓÚÜÑáéíóúüñ ]{2,40}?)\s*::\s*(-?[\d.,]+)\s*(\w{0,12})\s*$", re.M)


class MetricasSkill(Skill):
    name = "metricas"
    description = "Jala numeros: vitales del sistema y metricas registradas en el vault."
    triggers = [
        r"\bm[eé]tricas?\b", r"\bn[uú]meros?\b", r"\bvitales\b", r"\bestad[ií]sticas?\b",
        r"\bstatus\b", r"\bestado del (sistema|equipo)\b", r"\bcu[aá]nt[oa]s?\b",
        r"\bkpi\b", r"\brendimiento\b", r"\bcpu\b", r"\bmemoria ram\b",
    ]

    # -- vitales del sistema ------------------------------------------
    def system_vitals(self) -> dict[str, Any]:
        v: dict[str, Any] = {}
        try:
            import psutil
            v["cpu"] = psutil.cpu_percent(interval=0.15)
            v["cpu_cores"] = psutil.cpu_count(logical=True)
            mem = psutil.virtual_memory()
            v["ram"] = mem.percent
            v["ram_used_gb"] = round(mem.used / 1e9, 1)
            v["ram_total_gb"] = round(mem.total / 1e9, 1)
            try:
                freq = psutil.cpu_freq()
                v["cpu_ghz"] = round(freq.current / 1000, 2) if freq else None
            except Exception:
                v["cpu_ghz"] = None
            bat = getattr(psutil, "sensors_battery", lambda: None)()
            if bat:
                v["battery"] = round(bat.percent)
                v["plugged"] = bool(bat.power_plugged)
            net = psutil.net_io_counters()
            v["net_sent_mb"] = round(net.bytes_sent / 1e6, 1)
            v["net_recv_mb"] = round(net.bytes_recv / 1e6, 1)
            v["uptime_h"] = round((datetime.now().timestamp() - psutil.boot_time()) / 3600, 1)
            v["procs"] = len(psutil.pids())
        except ImportError:
            v["note"] = "psutil no instalado"
        try:
            du = shutil.disk_usage("C:\\")
            v["disk"] = round(du.used / du.total * 100, 1)
            v["disk_free_gb"] = round(du.free / 1e9, 1)
        except OSError:
            pass
        return v

    # -- metricas del vault -------------------------------------------
    def vault_metrics(self, ctx: SkillContext) -> dict[str, Any]:
        key = self.opts.get("frontmatter_key", "metric")
        found: dict[str, Any] = {}
        for note in ctx.vault.all_notes():
            if key in note.meta:
                found[str(note.meta.get("title") or note.title)] = note.meta[key]
            for k, val, unit in INLINE_METRIC.findall(note.body):
                name = k.strip()
                if not name or name.lower() in ("http", "https"):
                    continue
                try:
                    num = float(val.replace(",", "."))
                except ValueError:
                    continue
                prev = found.get(name)
                found[name] = f"{num:g}{(' ' + unit) if unit else ''}"
                if prev is not None:
                    found[name] = found[name]
        return found

    async def run(self, ctx: SkillContext) -> SkillResult:
        vitals = self.system_vitals() if self.opts.get("include_system", True) else {}
        vm = self.vault_metrics(ctx)
        vs = ctx.vault.stats()
        g = ctx.graph.build().to_json()

        lines = ["## Metricas", "", "### Sistema"]
        if vitals:
            ghz = f" @ {vitals['cpu_ghz']} GHz" if vitals.get("cpu_ghz") else ""
            lines += [
                f"- CPU **{vitals.get('cpu', '?')}%**{ghz} "
                f"({vitals.get('cpu_cores', '?')} hilos)",
                f"- RAM **{vitals.get('ram', '?')}%** — {vitals.get('ram_used_gb', '?')} / "
                f"{vitals.get('ram_total_gb', '?')} GB",
                f"- Disco C: **{vitals.get('disk', '?')}%** — {vitals.get('disk_free_gb', '?')} GB libres",
                f"- Uptime **{vitals.get('uptime_h', '?')} h** · {vitals.get('procs', '?')} procesos",
            ]
            if "battery" in vitals:
                lines.append(f"- Bateria **{vitals['battery']}%**"
                             f"{' (conectada)' if vitals.get('plugged') else ''}")
        else:
            lines.append("- sin lectura de sistema")

        lines += ["", "### Vault",
                  f"- **{vs['notes']}** notas · **{vs['links']}** enlaces · **{vs['tags']}** tags",
                  f"- **{vs['words']:,}** palabras · {vs['bytes'] / 1024:.0f} KB en disco",
                  f"- raw {vs['raw']} · wiki {vs['wiki']} · outputs {vs['outputs']}",
                  f"- grafo: {g['stats']['broken']} enlaces rotos · {g['stats']['orphans']} huerfanas"]

        if vm:
            lines += ["", "### Registradas"]
            lines += [f"- {k}: **{v}**" for k, v in sorted(vm.items())[:20]]

        speak = (f"CPU {vitals.get('cpu', '?')} por ciento, RAM {vitals.get('ram', '?')}. "
                 f"{vs['notes']} notas y {vs['links']} enlaces en el vault.")

        return SkillResult(
            speak=speak,
            display="\n".join(lines),
            data={"vitals": vitals, "vault": vs, "graph": g["stats"], "metrics": vm},
        )
