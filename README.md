# dictation — Ditado por voz para texto (Omarchy / Arch + Hyprland)

Aplicativo de ditado por voz: pressione `SUPER+H` para começar a gravar, pressione
novamente para transcrever e colar o texto na janela focada.

## Comportamento

1. `SUPER+H` → inicia a gravação do microfone (PipeWire) e mostra o overlay `SUPER+H`
2. `SUPER+H` de novo → para a gravação, transcreve e cola o texto na janela focada
3. Notificação mostra o texto final

## Indicador visual (overlay pílula)

Durante a gravação, uma pílula translúcida aparece na parte inferior central do
monitor ativo (15% da largura, 60px de altura):

- barras finas de 4px animadas com o nível ao vivo do microfone (escala dB,
  ataque rápido, decay lento, marcador branco no pico)
- azul `#4DA3FF` enquanto grava, vermelho `#E5484D` em espera
- some com fade-out ao parar

O indicador é o próprio gravador: lê o áudio via `pw-cat` (PipeWire nativo) e
mede o nível dos **mesmos bytes** que grava em `/tmp/dictation.wav`.

## Transcrição híbrida

1. **Groq API** (`whisper-large-v3-turbo`) — online, ~1s, precisão máxima
2. **fallback**: `faster-whisper` (`medium`, int8 CPU) — offline, sem depender de rede

O fallback é usado automaticamente quando a API está indisponível ou expira
(timeout configurável).

## Requisitos (Omarchy / Arch Linux)

Desenvolvido e testado em Omarchy 3.8.4 (Hyprland, Wayland). É necessário:

- `pipewire-utils` (pw-cat), `wl-clipboard` (wl-copy), `wtype` (digitação),
  `libnotify` (notificações), `python-gi` (GTK4) e `gtk4-layer-shell` (overlay)

## Instalação

1. Instale as dependências de sistema (ver acima)
2. Crie os ambientes Python:

```bash
python -m venv ~/.local/share/dictation/.venv
~/.local/share/dictation/.venv/bin/pip install -r requirements.txt
python -m venv --system-site-packages ~/.local/share/dictation/.venv-gui
```

3. Copie o projeto para `~/.local/share/dictation/` e crie um wrapper:

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/dictation <<'EOF'
#!/bin/bash
exec ~/.local/share/dictation/.venv/bin/python \
  ~/.local/share/dictation/dictation.py "$@"
EOF
chmod +x ~/.local/bin/dictation
```

## Configuração

Configuração do usuário em `~/.config/dictation/config.json` (secrets fora do
repositório). Principais chaves:

| chave | padrão | descrição |
|---|---|---|
| `groq_api_key_path` | `~/.config/dictation/groq.api.key` | chave da API Groq (arquivo com o texto puro da chave) |
| `groq_model` | `whisper-large-v3-turbo` | modelo online |
| `groq_timeout` | `30` | timeout da API em segundos |
| `fallback_model` | `medium` | modelo offline (faster-whisper, int8 CPU) |
| `fallback_cpu_threads` | `10` | threads do modelo offline |
| `language` | `null` | idioma (null = auto) |
| `indicator_enabled` | `true` | overlay ativo/inativo |
| `indicator_accent` | `#4DA3FF` | cor do overlay gravando |
| `indicator_idle` | `#E5484D` | cor do overlay em espera |
| `output` | `paste` | destino do texto (clipboard/paste) |

Atalho (Hyprland `bindings.conf`):

```conf
bind = SUPER, H, exec, dictation toggle
```

## Debug

Logs em `/tmp/dictation.log` (app) e `/tmp/dictation-indicator.log` (overlay).

## Notas

- **Wayland only** (wtype + overlay layer-shell); sem suporte a X11
- Suporte a outras distribuições Linux será desenvolvido separadamente
- Licença: MIT (ver LICENSE)