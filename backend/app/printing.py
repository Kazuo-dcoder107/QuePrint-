"""Wireless printer connectivity (FR14). In 'cups' mode jobs go to a CUPS/IPP printer with `lp`;
in 'simulate' mode nothing is printed (useful for demos and tests)."""
import subprocess
from . import config

MEDIA = {"A4": "A4", "A3": "A3", "Letter": "Letter", "Legal": "Legal"}


def send_to_printer(job) -> tuple[bool, str]:
    path = config.UPLOAD_DIR / job.print_name
    if not path.exists():
        return False, "The document file is missing from the server."
    if config.PRINTER_MODE != "cups":
        return True, "Simulated print (PRINTER_MODE=simulate)."
    cmd = ["lp", "-n", str(job.copies), "-t", job.tracking_code,
           "-o", f"media={MEDIA.get(job.paper_size, job.paper_size)}",
           "-o", "sides=two-sided-long-edge" if job.sides == "double" else "sides=one-sided",
           "-o", "print-color-mode=color" if job.color_mode == "color" else "print-color-mode=monochrome"]
    if config.PRINTER_NAME:
        cmd += ["-d", config.PRINTER_NAME]
    cmd.append(str(path))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return False, "Printing service (CUPS 'lp') is not installed on the server."
    except subprocess.TimeoutExpired:
        return False, "The printer did not respond in time."
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "The printer rejected the job.").strip()[:400]
    return True, r.stdout.strip()
