# File: app.py
# Project: CodeCraft AI
# Author: S. Sandhya (San-0602)

from pymongo import MongoClient
from datetime import datetime
from flask import Flask, render_template, request, send_file, redirect, url_for, session, flash
from flask_bcrypt import Bcrypt
import cohere
from fpdf import FPDF
import io
from dotenv import load_dotenv
import os
import random

# Load environment variables
load_dotenv()

# Flask setup
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Bcrypt
bcrypt = Bcrypt(app)

# MongoDB setup
client = MongoClient(os.getenv("MONGO_URI"))
db = client.codecraft
prompts_collection = db.prompts
users_collection = db.users

# Cohere setup
co = cohere.Client(os.getenv("COHERE_API_KEY"))

# Globals
generated_code = ""
explanation = ""
pair_prog_history = []
pdf_buffer = None

# Prompt builder
def build_prompt(ptype, diff, lang, top):
    return f"Generate a {diff.lower()} {ptype.lower()} project in {lang}. Topic: {top}. Include code, project report, and viva questions."

# PDF creation
def create_pdf(content):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for line in content.split('\n'):
        pdf.multi_cell(0, 10, line.encode('latin-1', 'replace').decode('latin-1'))
    buf = io.BytesIO(pdf.output(dest='S').encode('latin-1'))
    return buf

#Session reset
@app.route("/reset-session")
def reset_session():
    session.clear()
    print("Session cleared.")
    return "Session cleared."

# Root route
@app.route("/")
def root():
    return redirect(url_for("user_register"))

# User Registration
@app.route("/user-register", methods=["GET", "POST"])
def user_register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        existing_user = db.users.find_one({"username": username})

        if existing_user:
            flash("Username already exists.")
        else:
            hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
            db.users.insert_one({
                "username": username,
                "password": hashed_password,
                "joined_on": datetime.now()
            })
            flash("Registration successful! Please log in.")
            return redirect(url_for("user_login"))

    return render_template("user_register.html")

# User Login
code_samples = [
    "import numpy as np",
    "from sklearn.model_selection import train_test_split",
    "def train(model, data):",
    "    model.fit(data)",
    "print(\"Hello, AI!\")",
    "X = df[['feature1', 'feature2']]",
    "y = df['target']",
    "model.predict(new_data)",
    "plt.plot(x, y)",
    "torch.nn.ReLU()",
    "input().split()",
    "class Project:",
    "    def __init__(self):",
    "    def generate_code(self):",
    "json.loads(response)",
    "requests.get(url)"
]

@app.route("/user-login", methods=["GET", "POST"])
def user_login():
    code_positions = [
        {
            "top": random.randint(0, 100),
            "left": random.randint(0, 100),
            "code": random.choice(code_samples)
        } for _ in range(30)
    ]

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = db.users.find_one({"username": username})

        if user:
            stored_pw = user.get("password", "")
            if stored_pw.startswith("$2b$") and bcrypt.check_password_hash(stored_pw, password):
                session["user_logged_in"] = True
                session["user_name"] = username
                flash("Welcome back, " + username + "!")
                return redirect(url_for("splash"))
            else:
                flash("Invalid password or corrupted account. Please re-register.")
        else:
            flash("User not found. Please register first.")

    return render_template("user_login.html", code_positions=code_positions)

# Splash route
@app.route("/splash")
def splash():
    print("SPLASH session check:", session)
    if not session.get("user_logged_in"):
        print("Not logged in, redirect to login")
        return redirect(url_for("user_login"))
    print("Rendering splash screen")
    return render_template("splash.html")

# Home/index
@app.route("/home", methods=["GET", "POST"])
def index():
    global generated_code, explanation, pair_prog_history, pdf_buffer

    form_data = {
        "project_type": "",
        "difficulty": "",
        "language": "",
        "topic": ""
    }

    viva_questions = ""

    if request.method == "POST":
        form_data["project_type"] = request.form.get("project_type", "")
        form_data["difficulty"] = request.form.get("difficulty", "")
        form_data["language"] = request.form.get("language", "")
        form_data["topic"] = request.form.get("topic", "")
        action = request.form.get("action")
        user_question = request.form.get("user_question")
        hidden_code = request.form.get("generated_code", "")

        if not generated_code:
            generated_code = hidden_code

        if action == "generate":
            prompt = build_prompt(
                form_data["project_type"],
                form_data["difficulty"],
                form_data["language"],
                form_data["topic"]
            )
            response = co.generate(
                model='command-r-plus',
                prompt=prompt,
                max_tokens=4000,
                temperature=0.8,
            )
            generated_code = response.generations[0].text.strip()
            explanation = ""
            pdf_buffer = create_pdf(generated_code)
            pair_prog_history = []

            prompts_collection.insert_one({
                "project_type": form_data["project_type"],
                "difficulty": form_data["difficulty"],
                "language": form_data["language"],
                "topic": form_data["topic"],
                "timestamp": datetime.now()
            })

        elif action == "explain" and generated_code:
            explain_prompt = (
                f"Explain the following {form_data['language']} code in a detailed, step-by-step manner, "
                f"but ONLY explain the code itself. Do NOT include introductions, summaries, or implementation steps. "
                f"Just break down the code and its logic line by line:\n\n{generated_code}"
            )
            explanation_response = co.generate(
                model='command-r-plus',
                prompt=explain_prompt,
                max_tokens=2000,
                temperature=0.5,
            )
            explanation = explanation_response.generations[0].text.strip()

        elif action == "viva" and generated_code:
            viva_prompt = (
                f"Generate important viva or oral exam questions based on the following {form_data['language']} code:\n\n{generated_code}"
            )
            viva_response = co.generate(
                model='command-r-plus',
                prompt=viva_prompt,
                max_tokens=1000,
                temperature=0.7,
            )
            viva_questions = viva_response.generations[0].text.strip()

        elif action == "ask" and user_question and generated_code:
            pair_prompt = (
                f"You are an expert {form_data['language']} developer helping a user understand and improve their code.\n"
                f"The code is:\n{generated_code}\n\n"
                f"User question/request: {user_question}\n\n"
                f"Answer clearly, helpfully, and FORMAT the response using markdown where appropriate."
            )
            pair_response = co.generate(
                model='command-r-plus',
                prompt=pair_prompt,
                max_tokens=2000,
                temperature=0.7,
            )
            answer = pair_response.generations[0].text.strip()
            pair_prog_history.append((user_question, answer))

    return render_template("index.html",
        code=generated_code,
        explanation=explanation,
        viva_questions=viva_questions,
        history=pair_prog_history,
        form_data=form_data
    )
@app.route("/user-logout")
def user_logout():
    session.clear()
    flash("You’ve been logged out.")
    return redirect(url_for("user_login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == "admin" and password == "admin123":
            session["logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid admin credentials.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))

@app.route("/admin")
def admin_dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    prompts = list(prompts_collection.find().sort("timestamp", -1))
    return render_template("admin.html", prompts=prompts)

@app.route("/download")
def download():
    global pdf_buffer
    if pdf_buffer:
        pdf_buffer.seek(0)
        return send_file(pdf_buffer, as_attachment=True, download_name="CodeCraft_Project.pdf")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)