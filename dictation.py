#!/usr/bin/env python3
import argparse
import importlib.util
import json
import math
import os
import shutil
import signal
import stat
import struct
import subprocess
import sys
import time
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("DICTATION_CONFIG", "~/.config/dictation/config.json")).expanduser()

WAYBAR_SIGNAL = 11


def waybar_update():
    subprocess.run(["pkill", f"-RTMIN+{WAYBAR_SIGNAL}", "-x", "waybar"], check=False)


def beep(cfg, start=True):
    if not cfg.get("beeps", True):
        return
    freq = 880 if start else 660
    rate, dur, amp = 48000, 0.12, 0.25
    n = int(rate * dur)
    data = bytearray(n * 2)
    for i in range(n):
        v = int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate))
        data[i * 2:i * 2 + 2] = struct.pack("<h", v)
    try:
        subprocess.run(
            ["pw-cat", "--playback", "--raw", "--rate", str(rate), "--channels", "1",
             "--format", "s16", "--volume", "0.5", "-"],
            input=bytes(data), check=False, timeout=2,
        )
    except subprocess.TimeoutExpired:
        log_line("beep: pw-cat timeout (sink BT lento?)")

DEFAULTS = {
    "groq_api_key_path": "~/.config/dictation/groq.api.key",
    "groq_model": "whisper-large-v3-turbo",
    "groq_timeout": 30,
    "fallback_model": "medium",
    "fallback_cpu_threads": 10,
    "translate_model": None,
    "translate_prompt": "Translate to US English with correct punctuation.",
    "min_record_ms": 300,
    "template": None,
    "templates": {
        "megabrain": {
            "prefix": "O texto abaixo foi ditado por voz. Reescreva-o corrigindo pontuação, ortografia e estrutura, devolvendo apenas o resultado final, sem comentários:\n\n",
            "suffix": "",
        },
    },
    "language": None,
    "initial_prompt": "Este é um sistema de ditado por voz em português brasileiro. Transcreva exatamente o que foi falado, escrevendo todas as palavras completas, por extenso e com grafia e acentuação corretas — nunca omita ou corte letras. Não abreve nada. Use pontuação natural conforme a fala (vírgulas, ponto final, maiúsculas). Escreva números por extenso, a menos que o contexto seja claramente numérico ou técnico. Preserve nomes próprios, termos técnicos e gírias, grafados por completo. Ignore hesitações (hmm, ahn, éé, tipo) e repetições acidentais. Se um trecho estiver inaudível, escolha a palavra mais provável, completa, em vez de interromper o texto.",
    "output": "paste",
    "state_file": "/tmp/dictation.state",
    "audio_file": "/tmp/dictation.wav",
    "indicator_enabled": True,
    "indicator_width_pct": 0.15,
    "indicator_height": 60,
    "indicator_margin_bottom": 28,
    "indicator_accent": "#4DA3FF",
    "indicator_idle": "#E5484D",
}

PROJECT_DIR = Path(__file__).resolve().parent


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except Exception as e:
            notify("dictation", f"Config inválido ({CONFIG_PATH}): {e}", "critical")
    return cfg


def notify(app, body, urgency="normal", expire=5000):
    subprocess.run(["notify-send", "-a", app, "-u", urgency, "-t", str(expire), app, body], check=False)


def log_line(msg):
    try:
        with open("/tmp/dictation.log", "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def state_read(cfg):
    path = Path(cfg["state_file"])
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        pid = data.get("pid")
        if pid:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return None
            except PermissionError:
                pass
        return data
    except Exception:
        return None


def state_write(cfg, pid, translate=False, template=None):
    Path(cfg["state_file"]).write_text(
        json.dumps({"pid": pid, "started": time.time(), "translate": translate, "template": template})
    )


def state_clear(cfg):
    path = Path(cfg["state_file"])
    if path.exists():
        path.unlink()


def is_recording(cfg):
    return state_read(cfg) is not None


def active_monitor():
    try:
        out = subprocess.run(
            ["hyprctl", "activeworkspace", "-j"], capture_output=True, text=True, timeout=2
        )
        return json.loads(out.stdout).get("monitor")
    except Exception:
        return None


def layer_shell_preload():
    for p in ("/usr/lib/libgtk4-layer-shell.so", "/usr/lib64/libgtk4-layer-shell.so"):
        if os.path.exists(p):
            return p
    return None


def spawn_indicator(cfg):
    if not cfg.get("indicator_enabled", True):
        return None
    interp = PROJECT_DIR / ".venv-gui/bin/python"
    script = PROJECT_DIR / "indicator.py"
    if not interp.exists() or not script.exists():
        return None
    cmd = [
        str(interp), str(script),
        "--state-file", cfg["state_file"],
        "--audio-file", cfg["audio_file"],
        "--width-pct", str(cfg.get("indicator_width_pct", 0.25)),
        "--height", str(cfg.get("indicator_height", 56)),
        "--margin-bottom", str(cfg.get("indicator_margin_bottom", 28)),
        "--accent", cfg.get("indicator_accent", "#BE3F50"),
        "--idle", cfg.get("indicator_idle", "#14B9B5"),
    ]
    mon = active_monitor()
    if mon:
        cmd += ["--monitor", mon]
    log = open("/tmp/dictation.log", "a")
    env = os.environ.copy()
    preload = layer_shell_preload()
    if preload:
        env["LD_PRELOAD"] = f"{env.get('LD_PRELOAD', '')} {preload}".strip()
    proc = subprocess.Popen(
        cmd, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
        start_new_session=True, env=env,
    )
    return proc.pid


def kill_indicator(state):
    try:
        os.kill(state["pid"], signal.SIGTERM)
        for _ in range(50):
            try:
                os.kill(state["pid"], 0)
                time.sleep(0.1)
            except ProcessLookupError:
                break
        try:
            os.kill(state["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass


def start_recording(cfg, translate=False, template=None):
    if is_recording(cfg):
        notify("dictation", "Gravação já em andamento.", "normal")
        return
    audio = Path(cfg["audio_file"])
    audio.parent.mkdir(parents=True, exist_ok=True)
    if audio.exists():
        audio.unlink()
    pid = spawn_indicator(cfg)
    if not pid:
        notify("dictation", "Indicador indisponível (venv-gui ausente ou desabilitado).", "critical")
        return
    state_write(cfg, pid, translate, template)
    waybar_update()
    beep(cfg, start=True)
    log_line(f"record: pid={pid} translate={translate}")
    msg = "Gravando… (id. português → EN-US)" if translate else "Gravando…"
    notify("dictation", f"{msg} Pressione o atalho novamente para parar.", "normal")


def stop_recording(cfg, translate=False, template=None):
    state = state_read(cfg)
    if state is None:
        path = Path(cfg["state_file"])
        for _ in range(15):
            if path.exists():
                break
            time.sleep(0.1)
        state = state_read(cfg)
        if state is None and path.exists():
            try:
                data = json.loads(path.read_text())
                pid = data.get("pid")
                alive = False
                if pid:
                    try:
                        os.kill(pid, 0)
                        alive = True
                    except ProcessLookupError:
                        alive = False
                if not alive:
                    path.unlink()
                    waybar_update()
                    log_line("stop: state stale removido")
            except Exception:
                pass
        log_line(f"stop: state={'encontrado (poll)' if state else 'ausente'}")
    if state:
        if state.get("translate"):
            translate = True
        if state.get("template"):
            template = state["template"]
    audio = Path(cfg["audio_file"])
    if state is None and not audio.exists():
        notify("dictation", "Nenhuma gravação em andamento.", "normal")
        return
    if state:
        if time.time() - state.get("started", 0) < cfg.get("min_record_ms", 300) / 1000:
            kill_indicator(state)
            state_clear(cfg)
            if audio.exists():
                audio.unlink()
            waybar_update()
            notify("dictation", "Gravação muito curta — cancelada.", "normal")
            return
        kill_indicator(state)
        state_clear(cfg)
    waybar_update()
    beep(cfg, start=False)
    if not audio.exists() or audio.stat().st_size < 1000:
        log_line("stop: audio vazio/ausente")
        notify("dictation", "Gravação vazia — nada transcrito.", "critical")
        return
    text = transcribe(cfg, audio, translate=translate)
    log_line(f"stop: transcrito ({len(text or '')} chars)")
    if text:
        text = apply_template(cfg, text, template)
        output_text(cfg, text)
        body = f"Traduzido (EN-US): {text[:500]}" if translate else text[:500]
        notify("dictation", body)
    else:
        notify("dictation", "Não foi possível transcrever o áudio.", "critical")


def apply_template(cfg, text, template):
    if not template:
        return text
    tpl = (cfg.get("templates") or {}).get(template)
    if not tpl:
        notify("dictation", f"Template '{template}' não encontrado; sem template.", "normal")
        return text
    return f"{tpl.get('prefix', '')}{text}{tpl.get('suffix', '')}"


def transcribe(cfg, audio, translate=False):
    if translate:
        model = cfg.get("translate_model") or cfg["fallback_model"]
        try:
            return transcribe_local(cfg, audio, translate=True, model_name=model)
        except Exception as e:
            print(f"Tradução com {model} falhou ({e}); usando {cfg['fallback_model']}…", file=sys.stderr)
            notify("dictation", f"Modelo de tradução '{model}' indisponível; usando '{cfg['fallback_model']}'.", "normal")
            return transcribe_local(cfg, audio, translate=True, model_name=cfg["fallback_model"])
    key = load_groq_key(cfg)
    if key:
        for attempt in (1, 2):
            try:
                return transcribe_groq(cfg, audio, key)
            except Exception as e:
                print(f"Groq falhou (tentativa {attempt}: {e}); {'tentando novamente…' if attempt == 1 else 'usando fallback local…'}", file=sys.stderr)
                if attempt == 1:
                    time.sleep(0.5)
        notify("dictation", "Groq indisponível; usando transcrição local.", "low", expire=4000)
    else:
        notify("dictation", "Sem chave Groq; usando transcrição local.", "low", expire=4000)
    return transcribe_local(cfg, audio)


def load_groq_key(cfg):
    path = Path(cfg["groq_api_key_path"]).expanduser()
    if not path.exists():
        return None
    key = path.read_text().strip()
    return key or None


def transcribe_groq(cfg, audio, key):
    from groq import Groq

    client = Groq(api_key=key, timeout=cfg.get("groq_timeout", 30))
    kwargs = {}
    if cfg.get("language"):
        kwargs["language"] = cfg["language"]
    if cfg.get("initial_prompt"):
        kwargs["prompt"] = cfg["initial_prompt"]
    with open(audio, "rb") as f:
        result = client.audio.transcriptions.create(
            model=cfg["groq_model"],
            file=f,
            **kwargs,
        )
    return result.text.strip()


def transcribe_local(cfg, audio, translate=False, model_name=None):
    from faster_whisper import WhisperModel

    model = WhisperModel(
        model_name or cfg["fallback_model"],
        device="cpu",
        compute_type="int8",
        cpu_threads=cfg.get("fallback_cpu_threads", 10),
    )
    segments, _ = model.transcribe(
        str(audio),
        language=None if translate else cfg.get("language"),
        task="translate" if translate else "transcribe",
        beam_size=5,
        initial_prompt=cfg.get("translate_prompt") if translate else cfg.get("initial_prompt"),
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 600,
        },
    )
    return "".join(seg.text for seg in segments).strip()


def output_text(cfg, text):
    subprocess.run(["wl-copy", "--type", "text/plain"], input=text.encode(), check=False)
    if cfg.get("output") == "paste":
        subprocess.run(["wtype", "-"], input=text.encode(), check=False)


def doctor(cfg):
    results = []

    def report(level, label, msg):
        results.append((level, f"{label}: {msg}"))

    venv = PROJECT_DIR / ".venv/bin/python"
    venv_gui = PROJECT_DIR / ".venv-gui/bin/python"
    if venv.exists():
        report("ok", "venv app", f"existe ({venv})")
    else:
        report("err", "venv app", f"AUSENTE ({venv}) — pip install faster-whisper groq")
    if venv_gui.exists():
        report("ok", "venv indicador", f"existe ({venv_gui})")
    else:
        report("err", "venv indicador", "AUSENTE — recriar com --system-site-packages")

    for mod in ("groq", "faster_whisper"):
        if importlib.util.find_spec(mod) is not None:
            report("ok", f"módulo {mod}", "importável")
        else:
            report("err", f"módulo {mod}", "NÃO encontrado (pip install)")

    if venv_gui.exists():
        r = subprocess.run(
            [str(venv_gui), "-c", "import gi, numpy"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            report("ok", "venv indicador deps", "gi + numpy importáveis")
        else:
            report("err", "venv indicador deps", f"import falhou: {r.stderr.strip()[:200]}")

    for bin_name in ("pw-cat", "wl-copy", "wtype", "notify-send", "hyprctl"):
        if shutil.which(bin_name):
            report("ok", f"binário {bin_name}", shutil.which(bin_name))
        else:
            report("err", f"binário {bin_name}", "AUSENTE no PATH")

    key_path = Path(cfg.get("groq_api_key_path", DEFAULTS["groq_api_key_path"])).expanduser()
    if not key_path.exists():
        report("warn", "chave Groq", f"ausente ({key_path}) — apenas transcrição local")
    elif not key_path.read_text().strip():
        report("warn", "chave Groq", "arquivo vazio")
    else:
        mode = stat.S_IMODE(key_path.stat().st_mode)
        msg = "presente" + ("" if mode == 0o600 else f" (permissão {mode:o} — recomendo 600)")
        report("ok" if mode == 0o600 else "warn", "chave Groq", msg)

    if layer_shell_preload():
        report("ok", "layer-shell", f"({layer_shell_preload()})")
    else:
        report("err", "layer-shell", "libgtk4-layer-shell.so não encontrada — overlay não funcionará")

    hub = Path.home() / ".cache/huggingface/hub"
    for model in ("models--Systran--faster-whisper-medium",):
        if (hub / model).exists():
            report("ok", f"modelo {model}", "em cache")
        else:
            report("err", f"modelo {model}", "AUSENTE — baixar na 1ª transcrição local")
    translate_model = cfg.get("translate_model")
    if translate_model:
        name = "models--Systran--faster-whisper-large-v3"
        report("ok" if (hub / name).exists() else "warn", f"modelo {name}", f"(translate_model={translate_model})" if (hub / name).exists() else "AUSENTE — modo tradução usará fallback")

    if CONFIG_PATH.exists():
        try:
            json.loads(CONFIG_PATH.read_text())
            report("ok", "config", str(CONFIG_PATH))
        except Exception as e:
            report("err", "config", f"JSON inválido: {e}")
    else:
        report("warn", "config", f"ausente ({CONFIG_PATH}) — usando defaults")

    state_path = Path(cfg["state_file"])
    if state_path.exists() and state_read(cfg) is None:
        report("warn", "estado", "arquivo órfão (pid morto) — rodar `dictation stop`")
    else:
        report("ok", "estado", "consistente" if not state_path.exists() else "ativo")

    wb = Path.home() / ".config/waybar/dictation-status.py"
    if wb.exists() and os.access(wb, os.X_OK):
        report("ok", "waybar script", str(wb))
    else:
        report("warn", "waybar script", f"ausente ou sem exec ({wb})")

    errs = sum(1 for lvl, _ in results if lvl == "err")
    warns = sum(1 for lvl, _ in results if lvl == "warn")
    for lvl, line in results:
        icon = {"ok": "OK", "warn": "AVISO", "err": "ERRO"}[lvl]
        print(f"[{icon:>5}] {line}")
    print(f"\n{len(results)} checagens: {errs} erro(s), {warns} aviso(s).")
    return 2 if errs else (1 if warns else 0)


def main():
    parser = argparse.ArgumentParser(prog="dictation", description="Dictation app: voice to text")
    parser.add_argument("action", choices=["toggle", "record", "stop", "indicator", "templates", "doctor"])
    parser.add_argument(
        "-t", "--translate", action="store_true",
        help="Ditado PT-BR → EN-US (offline via faster-whisper, sem custo)",
    )
    parser.add_argument(
        "-T", "--template", default=None,
        help="Aplica um template (prefixo/sufixo) à transcrição (ex.: megabrain)",
    )
    args = parser.parse_args()
    cfg = load_config()
    if args.action == "templates":
        names = list((cfg.get("templates") or {}).keys())
        print("Templates disponíveis: " + (", ".join(names) if names else "(nenhum)"))
        return
    if args.action == "doctor":
        sys.exit(doctor(cfg))
    if args.action == "record":
        start_recording(cfg, translate=args.translate, template=args.template)
    elif args.action == "stop":
        stop_recording(cfg, translate=args.translate, template=args.template)
    elif args.action == "indicator":
        pid = spawn_indicator(cfg)
        if not pid:
            notify("dictation", "Indicador indisponível (venv-gui ausente ou desabilitado).", "critical")
    else:
        if is_recording(cfg):
            stop_recording(cfg, translate=args.translate, template=args.template)
        else:
            start_recording(cfg, translate=args.translate, template=args.template)


if __name__ == "__main__":
    main()
