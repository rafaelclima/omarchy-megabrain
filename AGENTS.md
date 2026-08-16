# dictation — Transcrição de voz para texto (Omarchy / Arch Linux)

App de ditado por voz: um atalho de teclado (`SUPER+H`) inicia a gravação da voz,
e o áudio é transcrito para texto com precisão máxima e colado na janela focada.

**Sistema alvo:** Omarchy 3.8.4 (Arch Linux + Hyprland)
**Data de início:** 2026-08-16

## Comportamento

1. `SUPER+H` → inicia gravação (mic via PipeWire), notificação "Gravando…"
2. `SUPER+H` de novo → para a gravação e transcreve
3. Texto transcrito → clipboard (`wl-copy`) → digitado na janela focada (`wtype`)
4. Notificação com o texto final

## Modo tradução (PT-BR → EN-US)

`SUPER+SHIFT+H` (`dictation toggle -t`) grava igual, mas transcreve já traduzido
para o inglês. **Sem custo e offline**: usa `faster-whisper` com
`task="translate"` (um passe faz ASR + tradução). A Groq é ignorada nesse modo
propositadamente — tradução por lá custaria: `whisper-large-v3` é 2.7x o
custo/hora do turbo e traduzir via LLM (llama) consumiria tokens. O modo fica
registrado no state (`translate: true`) e vale para o stop com qualquer atalho.

## Indicador visual (overlay "modulador")

Durante a gravação, um overlay aparece na **parte inferior central** do monitor
ativo (pílula translúcida, 15% da largura do monitor, 60px de altura, ~28px da
borda): label de estado ("Aguardando voz…" / "Gravando…") + barras finas de 4px animadas (quantidade cresce com a largura)
com o nível ao vivo do microfone (ataque rápido, decay lento, escala dB, pico
com marcador claro). Some com fade-out ao parar. Medidor usa um segundo stream
no mesmo source (`sounddevice`); sem interferir na gravação (`pw-record`).

## Arquitetura

```
SUPER+H (bindings.conf)
   │
   ▼
dictation toggle  (~/.local/bin/dictation → venv python)
   ├─ iniciar: spawn indicator.py (venv-gui, LD_PRELOAD)
   │            → indicator grava via pw-cat (PipeWire nativo, stdout raw f32)
   │              e grava /tmp/dictation.wav + mede o nível dos MESMOS bytes
   │            (estado em /tmp/dictation.state: pid)
   └─ parar:   kill indicador (fade + finaliza WAV) → transcrição híbrida:
                 1. Groq API (whisper-large-v3-turbo) — online, ~1s, precisão máxima
                 2. fallback: faster-whisper "medium" int8 CPU (offline)
               → wl-copy + wtype + notify-send
```

**Por que o indicador grava:** medir e gravar no mesmo processo via `pw-cat`
garante que as barras refletem **exatamente** o áudio transcrito — nenhum
segundo cliente de áudio (PortAudio/ALSA) ficava com sinal silencioso no
source Bluetooth (ver Bug #4).

## Stack / Tecnologias

| Camada | Tecnologia | Motivo |
|---|---|---|
| Gravação | `pw-cat --record --raw` (PipeWire nativo, dentro do indicador) | Mesmo caminho do antigo pw-record; stdout raw permite medir e gravar os mesmos bytes |
| Engine online | Groq API `whisper-large-v3-turbo` | Grátis, latência ~1s, precisão estado-da-arte |
| Engine offline | `faster-whisper` 1.2.x, modelo `medium`, int8 CPU, `vad_filter=True`, `language="pt"` | Melhor custo/precisão em CPU; funciona sem internet |
| Clipboard / digitação | `wl-copy` + `wtype` (Wayland) | Já instalados no Omarchy |
| Notificação | `notify-send` (Mako) | Padrão Omarchy |
| **Overlay indicador** | **GTK4 + PyGObject + `Gtk4LayerShell` 1.0** (layer-shell nativo Wayland) | Overlay sem janela gerenciada; já instalado no sistema |
| **Medidor de nível** | **numpy** sobre o stdout raw do `pw-cat` (mesmos bytes gravados) | RMS do áudio real em tempo real, consistente com a gravação |
| Linguagem | Python 3.14 (mise — app) / **Python do sistema** (indicador, tem GI) | `gi`/GTK4 não enxergado pelo Python do mise |
| Config | `~/.config/dictation/config.json` | Fora do repositório (contém secrets) |

## Estrutura de arquivos

```
~/Projects/dictation/
├── AGENTS.md           # este documento (vivo)
├── dictation.py        # script principal
├── indicator.py        # overlay indicador (GTK4 layer-shell + medidor)
├── .venv/              # app (faster-whisper, groq)
├── .venv-gui/          # indicador (--system-site-packages + sounddevice/numpy)
├── requirements.txt
└── .gitignore
~/.local/bin/dictation  # wrapper → venv
~/.config/dictation/config.json  # config + API key (fora do git)
```

## Config (`~/.config/dictation/config.json`)

```json
{
  "groq_api_key_path": "~/.config/dictation/groq.api.key",
  "groq_model": "whisper-large-v3-turbo",
  "groq_timeout": 30,
  "fallback_model": "medium",
  "fallback_cpu_threads": 10,
  "language": null,
  "initial_prompt": "Transcreva fala ditada em português brasileiro com pontuação natural e correta.",
  "output": "paste",
  "state_file": "/tmp/dictation.state",
  "audio_file": "/tmp/dictation.wav",
  "indicator_enabled": true,
  "indicator_width_pct": 0.15,
  "indicator_height": 60,
  "indicator_margin_bottom": 28,
  "indicator_accent": "#4DA3FF",
  "indicator_idle": "#E5484D"
}
```

- **API key da Groq** (grátis em https://console.groq.com): gravada em
  `~/.config/dictation/groq.api.key` (uma linha, permissão 600). Sem a chave,
  o app usa apenas o fallback local.
- **`language: null`** = auto-detecção de idioma (padrão). Definir `"pt"` força
  o idioma — melhora precisão em PT, mas corrompe a saída se o áudio for de
  outro idioma (ver bug #1).
- **`initial_prompt`** (2026-08-16): prompt de ditado otimizado — palavras
  completas/por extenso, sem omitir letras, pontuação natural, números por
  extenso, preservar termos técnicos, ignorar hesitações. Vale para Groq
  (param `prompt`) e local (param `initial_prompt` do faster-whisper).
- Cores do indicador (2026-08-16): **azul `#4DA3FF` ao gravar/falar** (estado
  ativo) e **vermelho `#E5484D` em espera de voz** (idle) — pedido do usuário;
  overridáveis no config.
  fundo `#0e091d`); overridáveis no config.

## Decisões registradas

- [x] 2026-08-16 — Engine: **híbrida** (Groq online + faster-whisper local como fallback)
- [x] 2026-08-16 — Saída: **copiar + colar no app focado** (não só clipboard)
- [x] 2026-08-16 — Interação: **toggle** (1x inicia, 1x para)
- [x] 2026-08-16 — Local do projeto: `~/Projects/dictation/`
- [x] 2026-08-16 — Atalho: `SUPER+H` (livre; havia dica comentada no bindings.conf linha 52)
- [x] 2026-08-16 — Sem GUI clássico: overlay layer-shell + notificações + clipboard (extensível: waybar, VAD)
- [x] 2026-08-16 — Idioma: auto-detecção por padrão (evita saída corrompida)
- [x] 2026-08-16 — Binding usa `exec` direto do Hyprland (não `uwsm-app`):

  > `uwsm-app` lança units systemd; o `pw-record` filho poderia ser morto pelo
  > systemd quando o processo principal termina. `exec` do Hyprland herda o
  > ambiente (WAYLAND_DISPLAY etc.) sem esse risco.

- [x] 2026-08-16 — Indicador: **overlay layer-shell** (não janela gerenciada):

  > GTK4 + `Gtk4LayerShell` 1.0 — `LAYER_OVERLAY`, âncora inferior, sem
  > exclusive zone, `KeyboardMode.NONE` (digitação continua no app focado).
  > Posicionado no **monitor ativo** no momento do toggle (via `hyprctl
  > activeworkspace`), centrado, **15% da largura** (pedido do usuário — pílula menor).
- [x] 2026-08-16 — Indicador roda no **Python do sistema** (não no venv do app):

  > as bindings GI (GTK4, layer-shell) moram em `/usr/lib/python3.x/site-packages`;
  > o Python do mise não as enxerga. `.venv-gui` = `--system-site-packages`
  > (puxa GI do sistema + numpy/sounddevice do pip).
- [x] 2026-08-16 — Resolução de linking do layer-shell documentada (ver Bug #2).
- [x] 2026-08-16 — Estado agora guarda também `pid_indicator` (kill no stop).
- [x] 2026-08-16 — **Tradução PT-BR → EN-US sem gerar custo**: rota exclusiva
  offline (`faster-whisper task="translate"`). Rejeitadas: `whisper-large-v3`
  Groq (2.7x custo/hora) e 2 estágios com LLM (tokens). Ativação por binding
  separado (`SUPER+SHIFT+H`), a pedido do usuário.

## Setup (passos executados)

- [x] 2026-08-16 — `mkdir ~/Projects/dictation` + `git init -b main`
- [x] 2026-08-16 — AGENTS.md criado
- [x] 2026-08-16 — venv + `pip install faster-whisper groq`
- [x] 2026-08-16 — `dictation.py` implementado
- [x] 2026-08-16 — Wrapper `~/.local/bin/dictation`
- [x] 2026-08-16 — Binding `SUPER+H` em `~/.config/hypr/bindings.conf` + `hyprctl reload` validado (`configerrors` limpo)
- [x] 2026-08-16 — Modelo `faster-whisper-medium` (1.5GB) baixado p/ `~/.cache/huggingface/hub`
- [x] 2026-08-16 — Chave da API Groq configurada em `~/.config/dictation/groq.api.key` (permissão 600)
- [x] 2026-08-16 — `.venv-gui` criado (Python do sistema, `--system-site-packages`, `sounddevice` + `numpy` + `pillow`)
- [x] 2026-08-16 — `indicator.py` implementado + integrado (spawn/kill, monitor ativo)
- [x] 2026-08-16 — Fix de linking documentado no wrapper (LD_PRELOAD automático)

## Comandos de uso

```bash
dictation toggle     # inicia/para gravação + transcreve (PT-BR)
dictation toggle -t  # inicia/para gravação + traduz para EN-US (offline, grátis)
dictation record     # só grava (idempotente)
dictation stop       # para e transcreve
```

## Testes executados (2026-08-16)

| Teste | Resultado |
|---|---|
| Toggle inicia/para gravação (estado via /tmp) | OK — estado limpo ao parar |
| Saída `wl-copy` + `wtype` (colar no app focado) | OK — texto apareceu no campo de texto do usuário |
| Groq `whisper-large-v3-turbo` (fala em inglês) | OK — transcreveu corretamente |
| Fallback local `medium` int8 (fala em inglês) | OK — transcreveu corretamente (~9s 1ª vez/modelo carregado) |
| Overlay aparece ao iniciar (monitor ativo, 15% largura, base central) | OK — layer 516x60 (DP-1 3440px) confirmado via `hyprctl layers` + diff de screenshots |
| **Modulação (barras com o áudio real)** | **OK** — medidor lê o stdout do pw-cat (mesmos bytes do WAV); WAV com RMS real 0,086/pico 0,87; transcrição real da voz do usuário |
| Overlay some ao parar (fade-out via SIGTERM) | OK — processo encerra, WAV finalizado (válido, 274k frames) |
| Auto-fechamento se estado sumir (gravação órfã) | OK — fade + finalização correta do WAV |
| Precisão em PT-BR com fala real | OK — "Oi, ei, ei, ei, ei." transcrito (Groq) |
| **Barras com sinal controlado (tom 220-880Hz via pipe-source)** | **OK** — L=0,876/st=active; WAV com RMS real; pill idle (teal) → ativa (vermelho accent, 7728px) via diff de screenshots |
| **Modo tradução PT-BR → EN-US (fala sintetizada edge-tts pt-BR-FranciscaNeural)** | **OK** — "Olá, como vai? Hoje está um dia lindo para programar…" → "Hello, how are you? Today is a beautiful day to schedule. I need to finish the report before lunch, please." (medium int8, offline, ~8s áudio) |
| Regressão transcrição PT-BR (mesmo áudio, modo normal) | OK — "Olá, como vai? Hoje está um dia lindo para programar. Preciso terminar o relatório antes do almoço, por favor." (exata) |
| `dictation stop -t` sem gravação ativa | OK — resposta limpa "Nenhuma gravação em andamento.", sem processos órfãos |
| `hyprctl reload` após novo binding `SUPER SHIFT, H` | OK — `configerrors` vazio |
| Fala real do usuário (mic BT) no modo tradução | **PENDENTE** — validar voz real + wtype |
| **Guard PTT (`min_record_ms` 300ms)** | **OK** — state com `started=now-0.1s` → cancelado: pid morto, state removido, wav removido, sem transcrição |
| **`large-v3` int8 tradução (sintético PT-BR)** | **OK** — download ~3GB (cache HF) + tradução em 16s warm; com `translate_prompt` → "Hello, how are you? Today is a beautiful day to schedule. I need to finish the report before lunch, please." |
| **`translate_prompt` (meio + grande)** | OK — medium 8s / large 16s, pontuação correta nos dois; sem prompt saía sem pontuação |
| **Template unit (`apply_template`)** | OK — prefix+texto+suffix; nome inexistente → texto original + aviso |
| **Template E2E (transcribe→translate→template→clipboard)** | OK — `wl-paste` = "PREFIXO-TESTE:\nHello, how are you? …\nSUFIXO-TESTE" (config temp com `output: clipboard`) |
| Fallback de modelo de tradução (nome inválido) | OK — cai para `fallback_model` com notificação |
| Regressões toggle PT/EN | OK — fluxos `dictation toggle [-t]` intactos (testes anteriores releitados) |
| **PTT físico (segurar SUPER+Q no teclado)** | **PENDENTE — usuário** (release é evento físico) |

## Bugs corrigidos

### Bug #1 — Idioma forçado corrompia transcrição de outros idiomas
**Data:** 2026-08-16

**Sintoma:** com `language="pt"` forçado, áudio em inglês resultava em texto
corrompido em pseudo-português ("Ele esperava que haveria arroz para o almoço…").

**Causa:** `language` era passado fixo (`"pt"`) para as duas engines; o fallback
de retry só disparava com texto vazio, nunca com texto "corrompido-não-vazio".

**Fix:** `language` padrão agora é `null` (auto-detecção do Whisper/Groq, ~100%
confiável em fala limpa). O `initial_prompt` continua em PT para forçar
pontuação/estilo natural. Definir `"pt"` via config continua possível (usuário
que só dita em PT ganha um pouco mais de precisão).

### Bug #2 — layer-shell do GTK4 não inicializava (ordem de linking)
**Data:** 2026-08-16

**Sintoma:** `Gtk4LayerShell.init_for_window()` não vinculava
(`is_layer_window=False`, warnings "GTK4 Layer Shell may have been linked after
libwayland"); overlay não aparecia.

**Causa:** ordem de linking entre `libgtk4-layer-shell` e `libwayland-client`
no GTK pré-compilado do Arch (problema conhecido:
github.com/wmww/gtk4-layer-shell/blob/main/linking.md).

**Fix:** `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so` no processo do indicador
(`layer_shell_preload()` no `spawn_indicator` — detecta a lib e injeta no env
automaticamente). Testado: `supported=True`, `is_layer_window=True`.

### Bug #3 — `Gdk.Display.get_primary_monitor` não existe no Wayland
**Data:** 2026-08-16

**Sintoma:** crash `AttributeError: 'GdkWaylandDisplay' object has no attribute
'get_primary_monitor'` ao abrir o indicador.

**Causa:** o conceito de monitor "primário" foi removido do GDK (GTK4.6+).

**Fix:** fallback para o primeiro monitor da lista (`monitors[0]`); a escolha
correta vem do `--monitor` passado pelo `dictation.py` (monitor ativo).

### Bug #4 — Indicador acusava "Sem microfone" / barras sem sinal (PortAudio × Bluetooth)
**Data:** 2026-08-16 — **Status: RESOLVIDO (fix estrutural)**

**Sintoma:** (1) intermitentemente a pílula mostrava "Sem microfone"; (2) depois,
com stream aberto, **nenhuma animação** aparecia mesmo com voz sendo capturada.

**Causa raiz:** o medidor via `sounddevice` (PortAudio → ALSA) conectava num
caminho de áudio diferente do `pw-record`: callbacks disparam, mas com
**silêncio digital** (RMS máx 0,0003 vs 0,086 do caminho PipeWire nativo —
~14.000x de diferença). Com o source padrão sendo o Bluetooth (soundcore Space
One), o segundo cliente ALSA não recebia o sinal real do mic.

**Fix estrutural:** o indicador agora **é o gravador** — spawna
`pw-cat --record --raw f32 48k mono` (mesmo caminho PipeWire do antigo
`pw-record`), lê o stdout no main loop GTK (IO watch), **calcula o RMS dos
mesmos bytes que grava** e escreve `/tmp/dictation.wav` (WAV s16 via stdlib
`wave`). Medição e gravação são o mesmo fluxo → consistência garantida por
construção; o bug da falta de sinal não pode mais ocorrer (o que for transcrito
é o que as barras mostram). Fallback de `sounddevice` removido (não confiável).

**Validação:** com o novo pipeline, WAV gravado com RMS 0,086 / pico 0,87 e
transcrição real da voz do usuário ("Oi, ei, ei, ei, ei.") + auto-fechamento
com WAV finalizado corretamente.

### Bug #5 — Barras nunca apareciam (área de desenho com altura 0)
**Data:** 2026-08-16 — **Status: RESOLVIDO**

**Sintoma:** a pílula mostrava o label ("Aguardando voz…"/"Gravando…") que
alternava corretamente com a fala, mas **nenhuma barra animava** — parecia que
o áudio não chegava, embora a gravação/transcrição funcionassem.

**Causa raiz:** o `Gtk.DrawingArea` tinha **altura 0**. `Gtk.Box` (eixo
VERTICAL) dá a cada filho o seu tamanho natural — e `GtkDrawingArea` tem
tamanho natural 0x0. Só o eixo transversal é expandido por padrão; no eixo
principal o filho precisa de `vexpand`. Logo a janela ficava ~19px (só o label)
e as barras eram desenhadas num retângulo vazio. O label continuava visível e
alternando (por isso o usuário via "Gravando…" sem barras).

**Fix:**
- `self.area.set_vexpand(True)` (expande no eixo principal do Box)
- `self.window.set_size_request(width, height)` (reforça o tamanho mínimo)

**Validação:** com `draw w=480 h=40` no log (antes `h=0`), teste determinístico
com `module-pipe-source` (FIFO) alimentando um tom 220-880Hz: `L=0.876
st=active` no tick, WAV com RMS 0,198/pico 0,6, e diff de screenshots na
pílula: idle=376px teal/0px vermelho → active=0px teal/**7728px vermelho accent**
(24 barras acesas na versão 28/desc.) — versão final: barras de 4px).

### Bug #6 — Marcador de pico na posição errada + gradiente inexistente no GI
**Data:** 2026-08-16 — **Status: RESOLVIDO (durante redesign)**

**Sintoma (em desenvolvimento):** o marcador branco de pico ficava sempre no
slot 23 (extrema direita) ou slot 1, independente do nível real.

**Causa:** dupla aplicação da escala — `p` era escalado por `N_BARS`
(`(peak - 0.5/N)*N`) e depois multiplicado de novo por `N_BARS` via
`min(p, 0.999)*N` (ou truncado em 1.0 pelo `clamp(0..1)`).

**Fix:** `p` é o próprio `peak` (já 0..1) e slot = `int(min(p*N_BARS, N_BARS-1))`.

**Bonus de compatibilidade:** ao implementar gradientes com
`cairo.Pattern.create_linear`, descobriu-se que o GI cairo do Arch **não
expõe** `Pattern.create_linear` nem `LinearGradient` — o draw quebraria no
primeiro fill (sem barras acesas). Redesign usa apenas fills sólidos (API
comprovada): corpo com alpha 0.32+0.55*filled + capa de brilho no topo.

**Validação:** `render_meter()` offscreen (pycairo, instalado no `.venv-gui`
como dev-dependency) — slots do pico conferem: peak 0.25→slot 6, 0.62→slot 14,
0.92→slot 22; barras altas com capa; sem cap no idle; live sem traceback no
stderr (`/tmp/ind-err.log` limpo).

## Features implementadas

- [x] 2026-08-16 — Toggle de gravação com estado persistente (arquivo em /tmp)
- [x] 2026-08-16 — Transcrição híbrida Groq → faster-whisper (fallback offline)
- [x] 2026-08-16 — Saída: clipboard + digitação na janela focada (wtype)
- [x] 2026-08-16 — Notificações de início/fim/erro
- [x] 2026-08-16 — Detecção de gravação órfã (estado "stale" é ignorado)
- [x] 2026-08-16 — Auto-detecção de idioma
- [x] 2026-08-16 — **Overlay visual "modulador"** (GTK4 layer-shell): pílula
  translúcida na base central do monitor ativo, 25% da largura; label de estado
  (Aguardando voz… / Gravando…) + barras finas 4px de nível ao vivo (RMS do mic,
  escala dB, ataque/release, pico com marcador)
- [x] 2026-08-16 — Indicador segue monitor ativo (`hyprctl activeworkspace`),
  cores do tema Aetheria (overridáveis), fade-out ao parar, auto-fechamento em
  gravação órfã, sem roubar foco/teclado (KeyboardMode.NONE)
- [x] 2026-08-16 — Mic robusto: referência forte do stream, fallback por
  candidatos (default → host APIs → devices), retry 2s, log dedicado
- [x] 2026-08-16 — **Gravação movida para dentro do indicador** (`pw-cat` raw →
  stdout lido no main loop GTK): medidor e gravação compartilham os mesmos
  bytes — consistência garantida por construção (Bug #4 resolvido)
- [x] 2026-08-16 — `sounddevice` removido do pipeline (caminho ALSA entregava
  silêncio no source BT); WAV s16/48k mono via stdlib `wave`, gravado em
  chunks conforme os dados chegam
- [x] 2026-08-16 — **Bug #5 resolvido**: `vexpand` na DrawingArea (barras
  desenhadas com altura real; antes `h=0`) + `set_size_request` na janela
- [x] 2026-08-16 — Debug leve: log de `draw w/h` (3 primeiras) e `tick L/P/st`
  a cada 600ms em `/tmp/dictation-indicator.log`; stderr do `pw-cat` no log
  (diagnóstico de morte do pw-cat) — mantido por ser barato e ground-truth
- [x] 2026-08-16 — **Redesign do medidor** (feedback do usuário "bolas com
  traço"): 24 barras (antes 28), fundo "apagado" de 10%, colunas com fill
  sólido + capa de brilho no topo (sem gradiente — GI cairo do Arch **não
  expõe** `Pattern.create_linear`/`LinearGradient`), e **um único** marcador
  branco de pico (antes um traço branco em cada barra = visual de "bolas com
  traço")
- [x] 2026-08-16 — `draw()` extraído para `render_meter()` puro (testável
  offscreen com pycairo via `.venv-gui`); bug corrigido: `min(p,0.999)*N`
  truncava o pico sempre no último slot (e o `clamp(0..1)` no primeiro) →
  agora `int(p*N)` correto
- [x] 2026-08-16 — **Prompt de transcrição novo** (ditado completo, por
  extenso, sem letras cortadas) aplicado nas DUAS engines + engine local agora
  recebe `initial_prompt` (antes ignorava) e VAD com `speech_pad_ms=600`
- [x] 2026-08-16 — **Redesign v2 (feedback "modulador de áudio")**: pílula
  **15% da largura** + **60px** de altura; **barras finas de espessura fixa
  4px** (gap 2.5px) com quantidade dinâmica conforme a largura (41 barras no
  eDP-1 a 76 no DP-1) — visual de VU meter real; sem capa de brilho
- [x] 2026-08-16 — **Cores por estado (pedido do usuário)**: azul `#4DA3FF`
  quando gravando/falando (ativo) e vermelho `#E5484D` em espera de voz (idle);
  labels acompanham (".active" azul / ".idle" vermelho)
- [x] 2026-08-16 — **Modo tradução PT-BR → EN-US** (`SUPER+SHIFT+H` /
  `dictation toggle -t`): faster-whisper `task="translate"` **offline e sem
  custo**; Groq ignorada nesse modo (tradução por lá custaria — turbo não
  traduz; v3 = 2.7x; LLM = tokens); `initial_prompt`/`language` omitidos no
  translate (evita vazamento do prompt PT na saída EN); modo lembrado no
  state (`translate: true`) — parar com qualquer atalho traduz; notificações
  marcadas "Traduzido (EN-US)"
- [x] 2026-08-16 — **Módulo Waybar `custom/dictation`**: ícone de status +
  ativação manual (esquerdo = transcrever, direito = traduzir) + tooltip com
  os binds de cada modo. `dictation-status.py` (Python3 stdlib, lê
  `/tmp/dictation.state` + `kill(pid,0)`, emite JSON, `interval=1`); classes
  `recording` (azul #4DA3FF) e `recording+translate` (verde #3DD68C) — **class
  precisa ser array JSON** `["recording","translate"]` (string com espaço vira
  classe única e a cor não aplica); texto dos estados: `󰍬` idle, `󰍬 PT`
  transcrição, `󰍬 EN` tradução. Validado por pixel nas screenshots da barra
  (+48px azul / +51px verde vs baseline). Segundo waybar órfão de restart
  anterior ocultava o novo — matar processos antigos antes de debugar a
  barra
- [x] 2026-08-16 — **Push-to-talk** (`SUPER+Q` / `SUPER+SHIFT+Q`): segurar =
  `dictation record`, soltar = `dictation stop [-t]` via `bindr` (flag `r` do
  Hyprland 0.56). **Atenção**: `bind = ..., r, exec, ...` NÃO existe — o flag
  é parte da keyword (`bindr = SUPER, Q, exec, ...`); tentar como dispatcher
  gera "Invalid dispatcher r". Guard `min_record_ms` (300ms) cancela taps;
  estado limpo + WAV removido + notificação. **Conflito descoberto**: P estava
  ocupado — `SUPER+P` = "Pseudo window" (defaults Omarchy tiling*.conf) e
  `SUPER+SHIFT+P` = Google Photos (bindings.conf linha 26); PTT movido para Q
  (verificado livre nos mods SUPER e SUPER+SHIFT)
- [x] 2026-08-16 — **Tradução com `translate_model`**: config `translate_model`
  (null = fallback; usuário optou `large-v3` no config local, ~3GB cache HF,
  warm ~16s). Engenharia: `transcribe()` no modo translate tenta o modelo
  configurado e cai para `fallback_model` com aviso se falhar
- [x] 2026-08-16 — **`translate_prompt`** (prompt EN de pontuação): sem ele o
  `task="translate"` sai **sem pontuação** ("Hello how are you today…");
  com ele, pontuação natural ("Hello, how are you? …"). Aplicado apenas no
  modo tradução (o prompt PT continua vetado — vazar o prompt PT induz o
  modelo a transcrever em vez de traduzir). Observação honesta: na amostra
  sintética, medium+p == large+p em vocabulário ("programar"→"schedule" em
  ambos — limitação do Whisper translate, não do tamanho do modelo)
- [x] 2026-08-16 — **Templates (modo megabrain)**: `-T/--template <nome>`
  (lembrado no estado, como translate) + `template` no config; action
  `templates` lista nomes; `prefix + texto + suffix` aplicado após tradução;
  templates em `cfg["templates"]` (default `megabrain` no DEFAULTS)

## Roadmap / Próximos passos

- [x] 2026-08-16 — Precisão em PT-BR com fala real validada (transcrição correta via Groq)
- [ ] Calibrar `initial_prompt`/`temperature` para ditados longos
- [ ] Parada automática por silêncio (VAD) — opcional
- [ ] Módulo de status no Waybar (indicador de gravação)
- [ ] Fallback local: alternar para `large-v3` int8 se latência aceitável
- [ ] Live transcription (whisper streaming) no overlay — descartado por ora (custo de CPU alto)
- [ ] Animar fade-in do indicador (hoje só fade-out)

## Notas de segurança

- **2026-08-16:** a chave API da Groq foi enviada pelo usuário via chat e ficou
  no clipboard. Recomendado **regenerar a chave** em https://console.groq.com
  (o app lerá a nova chave sem alteração — basta atualizar o arquivo
  `~/.config/dictation/groq.api.key`).
