# 🎤 AI Interview Prep

An AI-powered mock interview platform built with React, FastAPI, and Gemini API.

## ✨ Features

- AI-generated interview questions
- Real-time mock interview sessions
- Gemini API integration
- Technical interview preparation
- React + TypeScript frontend
- FastAPI backend
- Responsive modern UI
- Authentication system
- Interview history tracking
- Docker support

## 📂 Project Structure

```text
backend/    FastAPI backend and API routes
frontend/   React + TypeScript frontend
database/   Database models and configuration
static/     Static assets
```

## Setup

1. Create backend environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Configure environment variables:

```powershell
Copy-Item .env.example .env
```

Add your Gemini API key inside `.env`.

3. Install frontend dependencies:

```powershell
cd frontend
npm install
```

4. Run backend server:

```powershell
uvicorn fastapi_app:app --reload
```

5. Run frontend server:

```powershell
cd frontend
npm run dev
```

Open `http://localhost:5173`

## 🛠 Tech Stack

### Frontend
- React
- TypeScript
- Tailwind CSS
- Vite

### Backend
- FastAPI
- Python
- SQLAlchemy

### AI
- Gemini API

### DevOps
- Docker
- Render Deployment

---

## 🌐 Live Demo

https://ai-interview-frontend-li9l.onrender.com

---

## 📸 Screenshot

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/3460a09c-5c83-485f-a9d7-f37ad1e76f1b" />
