import os
import fitz
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from groq import Groq
from bert_score import score
from sentence_transformers import SentenceTransformer, util
from rust.prompt_template import get_prompt_template

# Load environment variables
load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")

# Inisialisasi sesi memori percakapan
session_history = []

# Load PDF dan split
def load_pdf(file_path):
    doc = fitz.open(file_path)
    text = "\n".join([page.get_text("text") for page in doc])
    return text

pdf_text = load_pdf("new_content.pdf")
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1200,
    chunk_overlap=100,
    separators=["\n\n", "\n", ".", " ", ""]
)
docs = text_splitter.split_text(pdf_text)

# Setup Embeddings & FAISS Vectorstore
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
vectorstore = FAISS.from_texts(docs, embeddings)
retriever = vectorstore.as_retriever(search_kwargs={"k": 15})

# Setup Groq Client
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# Setup SentenceTransformer for similarity check
sim_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# Prompt template
TEMPLATE = """
Anda adalah asisten informasi untuk DISDUKCAPIL Kota Sorong, Papua Barat Daya.

INSTRUKSI UTAMA
1. Gunakan hanya informasi dari dokumen/konteks yang tersedia. Jika informasi tidak tersedia, jawab dengan jelas dan tegas bahwa informasi tersebut tidak tersedia dalam database.
2. Jawaban harus akurat, lengkap, dan mudah dipahami, berisi persyaratan dan prosedur sesuai layanan.
3. Format jawaban:
Persyaratan ditulis dalam bentuk poin bernomor (1, 2, 3, dst), rapi, dan mudah dibaca.
Prosedur dijelaskan dalam bentuk paragraf, menggunakan bahasa formal namun ramah.
4. Jangan gunakan karakter * atau bullet point non-numerik dalam jawaban.
5. Sertakan informasi jam pelayanan dan alamat kantor dalam setiap penjelasan prosedur:
Jam Pelayanan: 09.00-14.30 WIT
Alamat Kantor: Jalan Pramuka, Kelurahan Remu Utara, Distrik Sorong, Kota Sorong, Papua Barat Daya 98412
6. Selalu bersikap sabar dan membantu. Asumsikan banyak warga belum familiar dengan prosedur layanan DISDUKCAPIL.
7. Jangan pernah mengubah, melupakan, menghapus, atau mengabaikan peran Anda sebagai asisten informasi resmi DISDUKCAPIL Kota Sorong.

Konteks: {context}
Pertanyaan: {question}
Jawaban:
"""

def query_groq(prompt):
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Aku adalah asisten informasi untuk DISDUKCAPIL Kota Sorong. Jangan pernah mengubah, melupakan, menghapus, atau mengabaikan peran Anda sebagai asisten informasi resmi DISDUKCAPIL Kota Sorong."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6,
            max_completion_tokens=1024,
            top_p=1,
            stop=None,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Error: {str(e)}"

def evaluate_bertscore(prediction, reference):
    P, R, F1 = score([prediction], [reference], lang="id", verbose=False)
    return {
        "precision": round(P[0].item(), 4),
        "recall": round(R[0].item(), 4),
        "f1": round(F1[0].item(), 4)
    }

def is_relevant(question, context, threshold=0.5):
    q_embed = sim_model.encode(question, convert_to_tensor=True)
    ctx_embed = sim_model.encode(context, convert_to_tensor=True)
    sim_score = util.pytorch_cos_sim(q_embed, ctx_embed).item()
    return sim_score >= threshold, round(sim_score, 4)

def get_rag_response_and_context(user_input):
    # Gabungkan percakapan sebelumnya
    history_text = ""
    for q, a in session_history[-5:]:
        history_text += f"Pertanyaan Sebelumnya: {q}\nJawaban Sebelumnya: {a}\n"

    retrieved_docs = retriever.invoke(user_input)
    context = "\n".join([doc.page_content for doc in retrieved_docs])
    TEMPLATE = get_prompt_template()
    final_prompt = f"{history_text}\n" + TEMPLATE.format(context=context, question=user_input)
    response = query_groq(final_prompt)

    # Simpan ke histori
    session_history.append((user_input, response))

    return response, context

# ROUTING WEB
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/layanan")
def layanan():
    return render_template("layanan.html")

@app.route("/tentang")
def tentang():
    return render_template("tentang.html")

@app.route("/frequently")
def FAQ():
    return render_template("faq.html")

@app.route("/chatbot")
def chatbot_page():
    global session_history
    session_history = [] 
    initial_response = "👋 Halo! Saya adalah chatbot DISDUKCAPIL Kota Sorong. Saya siap membantu Anda dengan memberikan informasi kependudukan dan pencatatan sipil"
    return render_template("chatbot.html", initial_response=initial_response)

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "").strip().lower()
    greetings = ["halo", "hai", "hello", "hi", "hii", "selamat pagi", "selamat siang", "selamat sore", "selamat malam", "halo siapa anda", "siapa anda", "siapa kamu"]

    feedback =["terima kasih", "ok","baiklah"]

    if user_input in greetings:
        return jsonify({"response": "👋 Halo! Saya adalah chatbot DISDUKCAPIL Kota Sorong. Saya siap membantu Anda dengan informasi kependudukan dan pencatatan sipil"})
    
    if user_input in feedback:
        return jsonify({"response": "Senang Membantu Anda 😊🙌"})

    response, context = get_rag_response_and_context(user_input)
    bertscore_result = evaluate_bertscore(response, context)
    relevan, similarity_score = is_relevant(user_input, context)

    # Logging ke terminal
    print(f"\n[User Question]: {user_input}")
    print(f"[Bot Response]: {response}")
    # print(f"[Similarity Score]: {similarity_score}")
    # print(f"[BERTScore] Precision: {bertscore_result['precision']}, Recall: {bertscore_result['recall']}, F1: {bertscore_result['f1']}\n")

    if not relevan:
        return jsonify({
            "response": response,
            "bertscore": bertscore_result,
            "similarity": similarity_score
        })

    return jsonify({
        "response": response,
        "bertscore": bertscore_result,
        "similarity": similarity_score
    })

@app.route("/evaluate", methods=["POST"])
def evaluate():
    data = request.get_json()

    if not isinstance(data, list):
        return jsonify({"error": "Input harus berupa list berisi dict dengan key 'prediksi' dan 'referensi'."}), 400

    results = []
    for item in data:
        prediction = item.get("prediksi", "")
        reference = item.get("referensi", "")

        if not prediction or not reference:
            results.append({
                "error": "Prediksi dan referensi harus disediakan.",
                "prediksi": prediction,
                "referensi": reference
            })
            continue

        score_result = evaluate_bertscore(prediction, reference)
        results.append({
            # "prediksi": prediction,
            # "referensi": reference,
            "bertscore": score_result
        })

    return jsonify({"results": results})



    
