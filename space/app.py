"""Space Gradio ZeroGPU « rag-llm » : sert uniquement la génération de texte.

L'API FastAPI (Azure, CPU) fait la recherche et construit le prompt, puis appelle ce Space via
gradio_client (api_name="/generate"). Le modèle est chargé au niveau du module (une fois, sur CPU
puis déplacé sur GPU par ZeroGPU) ; seule `generate` réserve le GPU, pour une durée courte.

Non déployé pour l'instant (périmètre local) : à créer en Space privé, matériel « ZeroGPU ».
"""

import os
from threading import Thread

import gradio as gr
import spaces
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

MODEL_ID = os.environ.get("MODEL_ID", "mistralai/Ministral-3-8B-Instruct-2512-BF16")
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "600"))
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.1"))

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=torch.bfloat16)
model.to("cuda")


@spaces.GPU(duration=30)
def generate(system_prompt: str, user_prompt: str):
    """Génère la réponse en streaming (texte cumulé à chaque étape)."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True
    ).to("cuda")
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    kwargs = dict(**inputs, streamer=streamer, max_new_tokens=MAX_NEW_TOKENS,
                  do_sample=TEMPERATURE > 0, temperature=TEMPERATURE)
    Thread(target=model.generate, kwargs=kwargs).start()
    text = ""
    for piece in streamer:
        text += piece
        yield text


demo = gr.Interface(
    fn=generate,
    inputs=[gr.Textbox(label="Prompt système"), gr.Textbox(label="Message utilisateur")],
    outputs=gr.Textbox(label="Réponse"),
    api_name="generate",
    title="rag-llm (Nexalis) — génération seule",
)

if __name__ == "__main__":
    demo.queue().launch()
