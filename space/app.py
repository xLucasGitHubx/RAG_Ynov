"""Space Gradio ZeroGPU « rag-llm » : sert uniquement la génération de texte.

L'API FastAPI (CPU) fait la recherche et construit le prompt, puis appelle ce Space avec
gradio_client. Le modèle est chargé une fois au niveau du module ; seules les fonctions
décorées @spaces.GPU réservent le GPU, pour une durée courte (meilleure priorité dans la file).

Points d'API :
- /generate      : texte en streaming (cumulé à chaque étape), utilisé par l'assistant ;
- /generate_json : réponse complète + mesures (tokens, durée GPU, VRAM), pour les évaluations.

Variables du Space :
- MODEL_ID       : dépôt du modèle (défaut : Ministral 3 8B Instruct bf16) ;
- QUANTIZATION   : bf16 (défaut), int8 ou nf4 (bitsandbytes), pour l'itération 6 ;
- MAX_NEW_TOKENS, TEMPERATURE, GPU_DURATION.
"""

import json
import os
import time
from threading import Thread

import gradio as gr
import spaces
import torch
from transformers import (
    AutoTokenizer,
    BitsAndBytesConfig,
    Mistral3ForConditionalGeneration,
    TextIteratorStreamer,
)

MODEL_ID = os.environ.get("MODEL_ID", "mistralai/Ministral-3-8B-Instruct-2512-BF16")
QUANTIZATION = os.environ.get("QUANTIZATION", "bf16").lower()
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "600"))
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.1"))
GPU_DURATION = int(os.environ.get("GPU_DURATION", "30"))

# fix_mistral_regex : sans ce drapeau, le tokenizer de Ministral 3 découpe mal certains textes.
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, fix_mistral_regex=True)

quantization_config = None
if QUANTIZATION == "int8":
    quantization_config = BitsAndBytesConfig(load_in_8bit=True)
elif QUANTIZATION == "nf4":
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16
    )

model = Mistral3ForConditionalGeneration.from_pretrained(
    MODEL_ID,
    dtype=torch.bfloat16,
    quantization_config=quantization_config,
    device_map="cuda" if quantization_config else None,
)
if quantization_config is None:
    model.to("cuda")
model.eval()


def _inputs(system_prompt: str, user_prompt: str) -> dict:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    encoded = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True
    )
    return {k: v.to("cuda") for k, v in encoded.items()}


def _generation_kwargs(inputs: dict) -> dict:
    sample = TEMPERATURE > 0
    return dict(
        **inputs,
        max_new_tokens=MAX_NEW_TOKENS,
        do_sample=sample,
        temperature=TEMPERATURE if sample else None,
        pad_token_id=tokenizer.eos_token_id,
    )


@spaces.GPU(duration=GPU_DURATION)
def generate(system_prompt: str, user_prompt: str):
    """Réponse en streaming : le texte cumulé est renvoyé à chaque nouveau morceau."""
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    kwargs = _generation_kwargs(_inputs(system_prompt, user_prompt))
    Thread(target=model.generate, kwargs={**kwargs, "streamer": streamer}).start()
    text = ""
    for piece in streamer:
        text += piece
        yield text


@spaces.GPU(duration=GPU_DURATION)
def generate_json(system_prompt: str, user_prompt: str) -> str:
    """Réponse complète et mesures, en JSON (évaluations, comparaison des quantizations)."""
    inputs = _inputs(system_prompt, user_prompt)
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    start = time.perf_counter()
    with torch.inference_mode():
        output = model.generate(**_generation_kwargs(inputs))
    torch.cuda.synchronize()
    seconds = time.perf_counter() - start
    prompt_tokens = inputs["input_ids"].shape[1]
    new_tokens = output[0][prompt_tokens:]
    return json.dumps({
        "text": tokenizer.decode(new_tokens, skip_special_tokens=True).strip(),
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(new_tokens.shape[0]),
        "generation_seconds": round(seconds, 3),
        "tokens_per_second": round(new_tokens.shape[0] / seconds, 2) if seconds else None,
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 2),
        "model": MODEL_ID,
        "quantization": QUANTIZATION,
        "gpu": torch.cuda.get_device_name(0),
    }, ensure_ascii=False)


with gr.Blocks(title="rag-llm — Nexalis") as demo:
    gr.Markdown(
        f"## rag-llm — génération pour l'assistant Nexalis\n"
        f"Modèle : `{MODEL_ID}` ({QUANTIZATION}). Space appelé par l'API, pas d'interface publique."
    )
    system = gr.Textbox(label="Prompt système", lines=3)
    user = gr.Textbox(label="Message utilisateur", lines=6)
    with gr.Row():
        run = gr.Button("Générer", variant="primary")
        run_json = gr.Button("Générer avec mesures")
    answer = gr.Textbox(label="Réponse", lines=8)
    run.click(generate, inputs=[system, user], outputs=answer, api_name="generate")
    run_json.click(generate_json, inputs=[system, user], outputs=answer, api_name="generate_json")

if __name__ == "__main__":
    demo.queue(max_size=20).launch()
