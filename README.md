# Humanizer AI Engine

FastAPI backend and web interface for rewriting AI-generated text while preserving Markdown formatting, code blocks, lists, and tables.

## Overview

Humanizer AI Engine processes text documents to make AI-generated text sound more natural without destroying document structure. Input text is parsed into an Abstract Syntax Tree (AST) to separate prose nodes from code blocks, tables, LaTeX math, and links. Only prose text is sent to LLM providers for rewriting, after which the document is reassembled automatically.

## Key Features

- Layout preservation: Keeps Markdown formatting, fenced code blocks, tables, LaTeX math, and bullet lists intact during rewriting.
- Multi-provider LLM routing: Configured to route requests to DeepSeek R1/V3, Gemini 1.5 Pro, Groq, or OpenRouter with fallback support.
- Text metrics: Calculates text perplexity, burstiness, and vocabulary variation before and after processing.
- Inline diff visualizer: Web component for comparing original and rewritten text side by side.
- Async API backend: Built on FastAPI with Pydantic request validation and SQLite/PostgreSQL storage.

## Tech Stack

- Backend: FastAPI, Uvicorn, Pydantic, SQLAlchemy, Asyncio
- LLM APIs: DeepSeek, Google Gemini, Groq, OpenRouter
- Database: SQLite, PostgreSQL
- Frontend: React, Vite

## Setup and Installation

### Prerequisites

- Python 3.11 or higher
- Node.js 18 or higher (for frontend)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/nabaraj-kc/Humanizer-AI-Engine.git
   cd Humanizer-AI-Engine
   ```

2. Create a virtual environment and install backend dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   ```bash
   cp .env.example .env
   # Add your API keys for OpenRouter, Gemini, DeepSeek, or Groq
   ```

4. Run the API server:
   ```bash
   python main.py
   # Server runs at http://localhost:8000
   ```
