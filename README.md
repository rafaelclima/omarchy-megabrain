# dictation — Ditado por voz para texto (Omarchy / Arch + Hyprland)

Aplicativo de ditado por voz: pressione `SUPER+H` para começar a gravar, pressione
novamente para transcrever e colar o texto na janela focada.

## Comportamento

1. `SUPER+H` → inicia a gravação do microfone (PipeWire) e mostra o overlay `SUPER+H`
2. `SUPER+H` de novo → para a gravação, transcreve e cola o texto na janela focada
3. Notificação mostra o texto final

## Modo tradução (PT-BR → EN-US)

`SUPER+SHIFT+H` grava como o normal, mas a transcrição sai traduzida para o
inglês (EN-US), colada no app focado.

- **100% offline e sem custo:** usa o `faster-whisper` com `task="translate"` —
  um único passe faz reconhecimento + tradução direto para o inglês.
  A rota online (Groq) é propositalmente ignorada nesse modo: o endpoint de
  tradução da Groq exige `whisper-large-v3` (2.7x o custo/hora do turbo) e
  traduzir via LLM consumiria tokens.
- O modo real é lembrado no estado: parando com `SUPER+H` ou `SUPER+SHIFT+H`,
  o resultado acompanha como a gravação começou.
- Modelo: `translate_model` (padrão `large-v3`, ~3GB download no 1º uso;
  `null` = usa `fallback_model`). Um prompt de pontuação em inglês
  (`translate_prompt`) é aplicado só na tradução.
- Qualidade: boa (Whisper), com imperfeições ocasionais de vocabulário
  ("programar" → "schedule").

## Push-to-talk (segurar para gravar)

`SUPER+P` grava enquanto segurado: soltou, transcreve e cola. `SUPER+SHIFT+P`
faz o mesmo traduzindo para EN-US. O toggle (`SUPER+H`) continua disponível.

```conf
bindd = SUPER, P, Dictation PTT record, exec, dictation record
bindr = SUPER, P, exec, dictation stop
bindd = SUPER SHIFT, P, Dictation PTT record (EN), exec, dictation record
bindr = SUPER SHIFT, P, exec, dictation stop -t
```

Taps acidentais (< `min_record_ms`, padrão 300ms) são cancelados sem
transcrição.

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
| `translate_model` | `null` | modelo do modo tradução (`null` = usa `fallback_model`; ex. `large-v3`) |
| `translate_prompt` | prompt EN | prompt de pontuação usado apenas na tradução |
| `min_record_ms` | `300` | gravações mais curtas são canceladas (tap acidental) |
| `template` | `null` | template ativo por padrão (nome em `templates`) |
| `templates` | `megabrain` | dicionário de templates (`prefix`/`suffix`) |
| `language` | `null` | idioma (null = auto) |
| `indicator_enabled` | `true` | overlay ativo/inativo |
| `indicator_accent` | `#4DA3FF` | cor do overlay gravando |
| `indicator_idle` | `#E5484D` | cor do overlay em espera |
| `output` | `paste` | destino do texto (clipboard/paste) |

Atalho (Hyprland `bindings.conf`):

```conf
bind = SUPER, H, exec, dictation toggle
bind = SUPER SHIFT, H, exec, dictation toggle -t   # traduz para EN-US
bind = SUPER, P, r, exec, dictation record         # push-to-talk (ligado ao segurar)
bindr = SUPER, P, exec, dictation stop             # ... e solto para transcrever
```

## Templates (modo "megabrain")

Transcrições podem sair já formatadas como prompt de IA. `dictation templates`
lista os nomes; o template é escolhido por ditado (`-T <nome>`, lembrado no
estado) ou fixado no config (`template`). Definição:

```json
"templates": {
  "megabrain": {
    "prefix": "O texto abaixo foi ditado por voz. Reescreva-o corrigindo pontuação, ortografia e estrutura, devolvendo apenas o resultado final, sem comentários:\n\n",
    "suffix": ""
  }
}
```

O texto final = `prefix + transcrição + suffix`, aplicado após a tradução
quando ambos estão ativos.

## Indicador na Waybar

O módulo `custom/dictation` (em `~/.config/waybar/`) mostra o estado e permite
ativar os modos com o mouse:

- **ícone** `󰍬` => dica com os atalhos de cada modo (clique esquerdo transcreve, clique direito traduz)
- **gravação**: `󰍬 PT` em azul (transcrição) ou `󰍬 EN` em verde (tradução) — atualiza a cada 1s
- **tooltip**: mostra qual atalho corresponde a cada modo (SUPER+H / SUPER+SHIFT+H) e como parar

```jsonc
"custom/dictation": {
  "exec": "/home/SEU_USUARIO/.config/waybar/dictation-status.py",
  "return-type": "json",
  "interval": 1,
  "on-click": "dictation toggle",
  "on-click-right": "dictation toggle -t"
}
```

```css
#custom-dictation { min-width: 12px; margin: 0 0 0 7.5px; font-size: 12px; }
#custom-dictation.recording { color: #4da3ff; }
#custom-dictation.recording.translate { color: #3dd68c; }
```

Arquivos: o script de status vive no repo em `waybar/dictation-status.py`
(leia `/tmp/dictation.state` e emite JSON — só Python3 stdlib); copie para
`~/.config/waybar/` e adicione o bloco abaixo em `config.jsonc` (com as cores
de `style.css`):

## Debug

Logs em `/tmp/dictation.log` (app) e `/tmp/dictation-indicator.log` (overlay).

## Notas

- **Wayland only** (wtype + overlay layer-shell); sem suporte a X11
- Suporte a outras distribuições Linux será desenvolvido separadamente
- Licença: MIT (ver LICENSE)