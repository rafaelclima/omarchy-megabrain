#!/usr/bin/env python3
import json
import os
import sys

STATE_FILE = "/tmp/dictation.state"

MIC = "󰍬"


def state_read():
    try:
        data = json.loads(open(STATE_FILE).read())
        pid = data.get("pid")
        if pid:
            os.kill(pid, 0)
        return data
    except (OSError, ValueError, KeyError):
        return None


def emit(text, tooltip, cls=None):
    out = {"text": text, "tooltip": tooltip}
    if cls:
        out["class"] = cls
    print(json.dumps(out, ensure_ascii=False))
    sys.stdout.flush()


def main():
    state = state_read()
    if state:
        translate = state.get("translate")
        if translate:
            emit(
                f"{MIC} EN",
                "Dictation — Gravando (tradução PT-BR → EN-US)\n\n"
                "SUPER+SHIFT+H: parar e traduzir\n"
                "SUPER+H: parar e transcrever em PT-BR\n"
                "SUPER+Shift+Q: PTT — soltar o botão para traduzir\n\n"
                "Clique direito: parar e traduzir",
                ["recording", "translate"],
            )
        else:
            emit(
                f"{MIC} PT",
                "Dictation — Gravando (transcrição PT-BR)\n\n"
                "SUPER+H: parar e transcrever\n"
                "SUPER+SHIFT+H: parar e traduzir (EN-US)\n"
                "SUPER+Q: PTT — soltar o botão para transcrever\n\n"
                "Clique esquerdo: parar e transcrever",
                "recording",
            )
    else:
        emit(
            MIC,
            "Dictation\n\n"
            f"{MIC} PT  SUPER+H        Transcrever (PT-BR)\n"
            f"{MIC} EN  SUPER+SHIFT+H  Traduzir (EN-US)\n"
            f"{MIC} PT  SUPER+Q        PTT transcrever (segurar/soltar)\n"
            f"{MIC} EN  SUPER+SHIFT+Q  PTT traduzir (segurar/soltar)\n\n"
            "Clique esquerdo: transcrever\n"
            "Clique direito: traduzir",
        )


if __name__ == "__main__":
    main()
