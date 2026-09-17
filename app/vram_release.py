import requests


def loaded_ollama_models(client, timeout=5.0):
    response = requests.get(
        f"{client.base_url}/api/ps",
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    names = []
    for item in payload.get("models", []):
        name = str(item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def unload_ollama_model(client, model, timeout=15.0):
    model = str(model or "").strip()
    if not model:
        raise ValueError("An Ollama model name is required.")

    response = requests.post(
        f"{client.base_url}/api/generate",
        json={
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
        },
        timeout=timeout,
    )
    response.raise_for_status()


def release_ollama_vram(client, fallback_model="", timeout=15.0):
    try:
        models = loaded_ollama_models(client, timeout=min(float(timeout), 5.0))
    except requests.RequestException:
        fallback = str(fallback_model or "").strip()
        models = [fallback] if fallback else []

    released = []
    for model in models:
        unload_ollama_model(client, model, timeout=timeout)
        released.append(model)
    return released
