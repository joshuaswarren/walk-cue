# Walk Cue

One card. A short walk. Then you leave.

Type a city or ZIP code. Walk Cue reads the weather and the hour, then gives you a single cue: how long, what kind of walk, and why this moment is the one. A few nearby parks show up when a map search answers. The page is supposed to be the short part of going outside.

## Run

Python 3.11 or newer. No API keys.

```bash
python3 -m pip install -r requirements.txt && python3 -m walkcue
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

A virtualenv is the cleaner version of the same thing:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m walkcue
```

Mock mode is the default. Type a real city, or type **Anytown** for a fictional placeholder that skips geocoding and map search.

Copy `.env.example` to `.env` only when you want to change something. Real environment variables win over the file.

## A local model

The offline cue is deterministic: same weather, same hour, same text. It is what you get until you opt in.

To write the cue with an open-weight model, run any server that speaks `POST /v1/chat/completions`, then turn live mode on. [Ollama](https://ollama.com) with Gemma:

```bash
ollama pull gemma3
ollama serve
```

`.env`:

```
WALK_CUE_LLM_MODE=live
WALK_CUE_LLM_BASE_URL=http://127.0.0.1:11434/v1
WALK_CUE_LLM_MODEL=gemma3
```

Restart `python -m walkcue`. A base URL by itself does nothing while mode is `mock`, so a fresh clone never waits on a model that isn't running.

If the server is down, times out, or returns something that isn't a usable cue, the card falls back to the offline text and says so.

LM Studio and similar local servers use the same settings. A common LM Studio base URL is `http://127.0.0.1:1234/v1`. Set `WALK_CUE_LLM_MODEL` to the name that server expects. Leave `WALK_CUE_LLM_API_KEY` empty unless it requires a bearer token.

`WALK_CUE_HOST=0.0.0.0` listens beyond localhost so a phone on the same network can open the card.

## What a request does

The area is whatever you type at runtime. It is not saved on the server. The browser remembers the last area on this machine so the next open can go straight to a cue.

For any place other than the Anytown placeholder:

1. Open-Meteo geocoding resolves the city or postal code. The forecast API then supplies current conditions. Neither call needs a key.
2. Overpass looks for named parks, gardens, and nature reserves within a few kilometers. The request sends a `Walk Cue` user agent. If Overpass fails, Nominatim gets one bounded park search. If that fails too, you still get a walk.
3. The cue comes from the local model, or from the offline writer.

Anytown is not a map lookup. It uses the computer's clock, a fixed mild forecast, and three sample spots so the card can be tried with nothing else configured.

## Tests

```bash
python3 -m pip install -r requirements-dev.txt
pytest
```

## License

MIT. See [LICENSE](LICENSE).
