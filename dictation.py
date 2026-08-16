#!/usr/bin/env python3
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("DICTATION_CONFIG", "~/.config/dictation/config.json")).expanduser()

DEFAULTS = {
    "groq_api_key_path": "~/.config/dictation/groq.api.key",
    "groq_model": "whisper-large-v3-turbo",
    "groq_timeout": 30,
    "fallback_model": "medium",
    "fallback_cpu_threads": 10,
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


def state_write(cfg, pid, translate=False):
    Path(cfg["state_file"]).write_text(
        json.dumps({"pid": pid, "started": time.time(), "translate": translate})
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
    proc = subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True, env=env)
    return proc.pid


def start_recording(cfg, translate=False):
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
    state_write(cfg, pid, translate)
    msg = "Gravando… (id. português → EN-US)" if translate else "Gravando…"
    notify("dictation", f"{msg} Pressione o atalho novamente para parar.", "normal")


def stop_recording(cfg, translate=False):
    state = state_read(cfg)
    if state and state.get("translate"):
        translate = True
    audio = Path(cfg["audio_file"])
    if state is None and not audio.exists():
        notify("dictation", "Nenhuma gravação em andamento.", "normal")
        return
    if state:
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
        state_clear(cfg)
    if not audio.exists() or audio.stat().st_size < 1000:
        notify("dictation", "Gravação vazia — nada transcrito.", "critical")
        return
    text = transcribe(cfg, audio, translate=translate)
    if text:
        output_text(cfg, text)
        body = f"Traduzido (EN-US): {text[:500]}" if translate else text[:500]
        notify("dictation", body)
    else:
        notify("dictation", "Não foi possível transcrever o áudio.", "critical")


def transcribe(cfg, audio, translate=False):
    if translate:
        return transcribe_local(cfg, audio, translate=True)
    key = load_groq_key(cfg)
    if key:
        try:
            return transcribe_groq(cfg, audio, key)
        except Exception as e:
            print(f"Groq falhou ({e}); usando fallback local…", file=sys.stderr)
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


def transcribe_local(cfg, audio, translate=False):
    from faster_whisper import WhisperModel

    model = WhisperModel(
        cfg["fallback_model"],
        device="cpu",
        compute_type="int8",
        cpu_threads=cfg.get("fallback_cpu_threads", 10),
    )
    segments, _ = model.transcribe(
        str(audio),
        language=None if translate else cfg.get("language"),
        task="translate" if translate else "transcribe",
        beam_size=5,
        initial_prompt=None if translate else cfg.get("initial_prompt"),
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


def main():
    parser = argparse.ArgumentParser(prog="dictation", description="Dictation app: voice to text")
    parser.add_argument("action", choices=["toggle", "record", "stop", "indicator"])
    parser.add_argument(
        "-t", "--translate", action="store_true",
        help="Ditado PT-BR → EN-US (offline via faster-whisper, sem custo)",
    )
    args = parser.parse_args()
    cfg = load_config()
    if args.action == "record":
        start_recording(cfg, translate=args.translate)
    elif args.action == "stop":
        stop_recording(cfg, translate=args.translate)
    elif args.action == "indicator":
        pid = spawn_indicator(cfg)
        if not pid:
            notify("dictation", "Indicador indisponível (venv-gui ausente ou desabilitado).", "critical")
    else:
        if is_recording(cfg):
            stop_recording(cfg, translate=args.translate)
        else:
            start_recording(cfg, translate=args.translate)


if __name__ == "__main__":
    main()
