You are a Staff-level Machine Learning + AI Platform + Backend Engineer
with deep expertise in:

- Production LLM systems
- MLOps and evaluation pipelines
- Scalable backend architecture
- Google Cloud Platform
- Secure system design
- Long-term memory architectures for AI systems

Your task is to design and implement a production-grade AI Coaching Platform
using Google Vertex AI (Gemini models).

This system is initially single-user (for personal use),
but must be architected in a way that can scale to multi-user SaaS
without requiring a full rewrite.

You must justify major architectural decisions and explain tradeoffs.

If you believe Google ADK is more appropriate than direct Vertex AI usage,
you must explain why and provide a tradeoff analysis.

Before writing code, first outline system design decisions and tradeoffs.

--------------------------------------------------
SYSTEM GOAL
--------------------------------------------------

Build a "Professional AI Coach" platform for long-term personal and professional development.

This is NOT a toy chatbot.
It is a long-term adaptive AI system with:

- Persistent memory
- Structured planning logic
- Behavioral signal tracking
- Evaluation-driven prompt iteration
- Cost-aware LLM usage

--------------------------------------------------
DESIGN CONSTRAINTS
--------------------------------------------------

- Single authenticated user (for now)
- Clean internal separation between:
    - Domain logic
    - Planning logic
    - LLM orchestration
    - Memory layer
- No premature overengineering
- Minimal but production-correct infrastructure
- Designed for future multi-tenant extension

--------------------------------------------------
NON-FUNCTIONAL REQUIREMENTS
--------------------------------------------------

- Secure-by-design
- Observability-first
- Evaluation-driven development
- Cost-aware LLM usage
- Clean separation of concerns
- Structured, traceable logging
- Prompt versioning support

--------------------------------------------------
CORE FUNCTIONAL REQUIREMENTS
--------------------------------------------------

1. Authentication

- Google OAuth
- Session management
- Secure secrets handling
- PII-aware logging

Even though it is single-user, the design must allow future multi-user support.

--------------------------------------------------

2. Long-Term Memory Architecture

Structured relational database (PostgreSQL preferred unless justified otherwise).

Persist:

- Goals (short, quarterly, long-term)
- Skills
- Projects
- Weekly plans
- Reflections
- Progress metrics
- Coaching sessions
- Behavioral signals (completion rate, drift, burnout indicators)

Design:

- Proper schema normalization
- Indexing strategy
- Audit fields (created_at, updated_at)
- Versioning for critical entities

Explain:
- Why relational vs document DB
- How this would evolve for multi-user

Vector memory is optional in v1.
If included, justify its necessity.

--------------------------------------------------

3. AI Coaching Capabilities

The AI Coach must:

- Define SMART goals
- Decompose goals into quarterly → weekly → daily plans
- Suggest skill-building projects
- Suggest curated learning resources
- Be ADHD-aware in planning structure
- Provide structured reflection templates
- Detect stagnation patterns
- Detect overcommitment patterns
- Adjust tone based on behavioral signals

All LLM outputs must:

- Use strict JSON schema validation
- Be post-processed before persistence
- Never directly control core business logic

--------------------------------------------------

4. Planning Engine (Critical)

Separate deterministic planning logic from LLM outputs.

Implement:

- Prioritization algorithm
- Weekly time allocation logic
- Focus scoring
- Progress scoring
- Burnout risk heuristic

Explicitly define:
- What is deterministic
- What is LLM-assisted
- What must never depend purely on LLM output

--------------------------------------------------
VERTEX AI REQUIREMENTS
--------------------------------------------------

1. Model Integration

- Gemini via Vertex AI
- System prompts with strict role separation
- JSON schema enforcement
- Safety configuration
- Retry + exponential backoff
- Timeout handling

2. Logging & Observability (MANDATORY)

Log:

- Prompt version
- Model version
- Token usage
- Latency
- Trace ID
- Evaluation score
- Estimated cost per request

Use:

- Structured JSON logging
- Cloud Logging
- Cloud Trace
- Cost estimation utility

Logs must be analytics-ready.

--------------------------------------------------

3. Evaluation Framework (CRITICAL)

Design an evaluation-first workflow:

- Golden dataset of coaching scenarios
- Offline evaluation script
- LLM-as-judge scoring with rubric
- Regression testing before prompt updates
- Guardrail evaluation (tone, hallucination, harmful advice)

Explain:

- Prompt versioning strategy
- How evaluation integrates into CI/CD
- How A/B testing would work once multi-user

--------------------------------------------------

4. Cost Control Strategy

Include:

- Token budgeting per request
- Conversation window management
- Historical summarization strategy
- Memory compression approach
- Caching strategy for repeated queries

--------------------------------------------------
ARCHITECTURE REQUIREMENTS
--------------------------------------------------

Backend:

- Python (FastAPI preferred)
- Clean Architecture:
    - Domain layer
    - Application layer
    - Infrastructure layer
- Repository pattern
- Service abstraction for LLM calls
- Async-first design

Frontend:

- Minimal Python-based frontend preferred (Streamlit or FastAPI templates)
- Focus on usability over aesthetics
- Must include:
    - Goals view
    - Weekly plan view
    - Reflection logging
    - Progress visualization
    - Chat interface

Explain frontend choice tradeoffs.

--------------------------------------------------
INFRASTRUCTURE
--------------------------------------------------

- Cloud Run deployment
- Dockerized application
- Terraform IaC (minimal but correct)
- Secret Manager integration
- Basic CI/CD pipeline outline
- Environment configuration strategy

Avoid unnecessary microservices.

--------------------------------------------------
DATA MODEL REQUIREMENTS
--------------------------------------------------

Define production-grade schemas for:

- User
- Goal
- Skill
- Project
- WeeklyPlan
- Reflection
- CoachingSession
- BehavioralSignal
- EvaluationLog
- PromptVersion

Include:

- Field definitions
- Relationships
- Indexing strategy
- Normalization decisions

--------------------------------------------------
OUTPUT FORMAT (STRICT)
--------------------------------------------------

1. System Design Decisions & Tradeoffs (first)
2. High-Level Architecture Diagram (text)
3. Detailed Architecture Explanation
4. Folder Structure
5. Data Model Schemas
6. LLM Integration Layer Code
7. Logging + Evaluation Implementation
8. Example Structured System Prompt
9. CI/CD + Deployment Plan
10. Cost Strategy
11. Multi-User Evolution Plan

Do NOT provide toy examples.
Do NOT simplify.
Do NOT overengineer.
Design this like a real production system for a serious engineer.


Important:
Document your development in tech_coach/docs/ai_developments as markdown.
