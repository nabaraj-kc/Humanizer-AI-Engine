# Part 6: The 50-Stage Granular Implementation Plan

Execute these instructions sequentially in your Antigravity AI Code Editor environment. Do not jump stages; complete the structural code implementation, run the verification scripts inside your agent console, and ensure all unit checks pass cleanly before proceeding to the next file step.

---

### Phase 1: Structural Scaffolding & Database Tier (Stages 1-6)

#### Stage 1: Directory Tree & Workspace Initialization
* **Goal:** Initialize the project's root codebase, defining a modular Python package structure alongside clean, separate frontend asset directories.
* **Prompt for Antigravity Agent:**
    ```text
    Create the full project root directory tree structure for a modular FastAPI application. Generate the following directories: 'backend/', 'backend/app/', 'backend/app/api/', 'backend/app/core/', 'backend/app/services/', 'backend/app/db/', 'frontend/', 'frontend/css/', 'frontend/js/', and 'storage/'. Create empty configuration files initialized with standard python packaging structure: 'backend/app/__init__.py', 'backend/app/main.py', '.env.example', and 'requirements.txt'. Include an explicit validation check to verify that all directories exist on disk, reporting absolute paths to console.
    ```
* **Compulsory Verification Guardrail:** The agent must execute a custom python `os.path.exists()` diagnostic loop across all created paths. If any folder fails confirmation or permissions are blocked, the script must abort execution, trace the system error, and rewrite the missing nodes before concluding the step.

#### Stage 2: Core Dependencies Specification Configuration
* **Goal:** Define an exhaustive, lock-ready `requirements.txt` containing all versions for the underlying async web servers, ML transformers, and coordinate parsing engines.
* **Prompt for Antigravity Agent:**
    ```text
    Write a comprehensive 'requirements.txt' file for the project. Include explicit production versioning tags for: fastapi, uvicorn, pydantic, pydantic-settings, PyMuPDF, reportlab, torch, transformers, websockets, sqlalchemy, aiohttp, and cryptography. Add exhaustive inline commentary describing what role each package serves within the system ecosystem. Write a verification script that uses pip to run a dry-run check testing the dependency trees for installation conflicts.
    ```
* **Compulsory Verification Guardrail:** The agent must simulate package parsing. It must check for conflicting package dependencies—especially between `transformers`, `torch`, and asynchronous networking wrappers—and ensure all versions resolve properly without installation errors.

#### Stage 3: Asynchronous Database Core Initialization
* **Goal:** Setup an asynchronous SQLAlchemy engine configuration mapping directly to a resilient local SQLite instance file.
* **Prompt for Antigravity Agent:**
    ```text
    Develop 'backend/app/db/session.py'. Establish an asynchronous SQLAlchemy engine using 'sqlite+aiosqlite:///.../storage/humanizer.db'. Configure connection pool execution arguments to enforce SQLite foreign key constraints upon initialization ('PRAGMA foreign_keys = ON;'). Code an async session factory ('async_sessionmaker') ensuring 'expire_on_commit=False'. Create an integration test script that attempts to connect asynchronously, runs a trivial 'SELECT 1' test query, and asserts structural safety.
    ```
* **Compulsory Verification Guardrail:** The validation block must execute the test database script. If a locking contention, initialization block, or relative path error occurs, the agent must catch the exception, re-route the database file to an absolute path inside the `storage/` container, and verify the connection again.

#### Stage 4: Relational Data Models Declaration
* **Goal:** Declare declarative relational ORM database tables for tracking runs, text segments, and API quotas.
* **Prompt for Antigravity Agent:**
    ```text
    Create 'backend/app/db/models.py' using SQLAlchemy's Declarative Base. Implement three structured data models matching these specifications: 'ApiQuota' (provider, daily_limit, used_today, rpm_limit, last_reset), 'PaperRun' (run_id, filename, total_chunks, start_time, status, master_summary), and 'TextChunk' (chunk_id, run_id, sequence_no, raw_text, clean_text, processed, iterations). The master_summary column is NULLABLE TEXT, populated by the Global Context Extractor after initial PDF parsing and before the chunk rewriting loops begin. Setup foreign key relations and cascade delete constraints exactly. Include an automatic script that compiles these classes and checks schema generation syntax for compilation bugs.
    ```
* **Compulsory Verification Guardrail:** The agent must programmatically compile the ORM metadata against a temporary memory SQLite engine. If any column constraint, string mapping, or foreign key linkage contains type mismatch errors, the agent must inspect the model mappings and fix them.

#### Stage 5: Database Migration & Table Seeding Scripts
* **Goal:** Program an automated database schema migration initializer that seeds free-tier configurations for Google, Groq, and DeepSeek.
* **Prompt for Antigravity Agent:**
    ```text
    Develop an initialization service in 'backend/app/db/init_db.py'. This service must check if tables exist, create them if missing via metadata execution, and verify if seed data is present in 'api_quotas'. Seed default records for 'google' (limit 1000000), 'groq' (limit 14400), and 'deepseek' (limit 500000). Ensure the script handles duplicate keys gracefully by implementing an 'ON CONFLICT DO NOTHING' equivalent structure. Code a testing function to query and print the seeded table states.
    ```
* **Compulsory Verification Guardrail:** Run the initialization script. The code must confirm table creation by executing an explicit table inspection query (`PRAGMA table_info`). If data is missing or corruption occurs, wipe the testing environment state and rebuild the schemas.

#### Stage 6: Centralized Environment Settings Infrastructure
* **Goal:** Implement a strictly validated configuration framework parsing variables from a local `.env` setup file.
* **Prompt for Antigravity Agent:**
    ```text
    Create 'backend/app/core/config.py' utilizing 'pydantic_settings.BaseSettings'. Define mandatory system properties: 'DATABASE_URL', 'GOOGLE_API_KEY', 'GROQ_API_KEY', 'DEEPSEEK_API_KEY', and 'JWT_SECRET_KEY'. Apply strict Pydantic parsing ensuring missing configuration parameters raise clear, descriptive runtime errors during boot. Write a verification script that builds a sample config object, matching defaults while ensuring missing keys throw expected validation errors.
    ```
* **Compulsory Verification Guardrail:** The testing harness must attempt initialization with incomplete configuration states. The script must catch validation errors, ensure they are handled gracefully, and verify that the app will fail to start if key credentials are missing.

---

### Phase 2: PDF Parsing & Geometric Layout Tier (Stages 7-14)

#### Stage 7: PDF Document Layout Extraction Service
* **Goal:** Implement an optimized `PyMuPDF` text parsing wrapper to extract strings while tracking positional bounding coordinates.
* **Prompt for Antigravity Agent:**
    ```text
    Develop 'backend/app/services/pdf_extractor.py'. Implement a class 'PdfLayoutExtractor' that uses PyMuPDF ('fitz') to open an target document. Loop through pages extracting blocks via '.get_text("blocks")'. Capture text coordinates: X0, Y0, X1, Y1, block number, line number, and font attributes. Pack this information into a structured JSON schema. Create an automated unit test that runs a sample multi-line extraction loop, verifying coordinate types are floating-point numbers.
    ```
* **Compulsory Verification Guardrail:** The test routine must process a mock PDF matrix or text stream. If coordinates read as null, malformed integers, or missing structures, the extraction loop must catch the bad block, log the paragraph context, and assign default bounding constraints.

#### Stage 8: Regular Expression Citation Extraction Shield
* **Goal:** Build a robust regex parsing library designed to identify and extract inline citations, keeping them safe from modification.
* **Prompt for Antigravity Agent:**
    ```text
    Write a protective regex text module in 'backend/app/services/citation_shield.py'. Design complex regex patterns to match academic citation formats: bracketed sequences like '[1, 2]', numbers like '[14]', and textual references like '(Author, 2024)'. Implement a function 'shield_citations(text)' that extracts matches, caches them in a dynamic dictionary index with safe substitution tokens like '__CITATION_IDX__', and returns a sterilized text string. Write an inversion function to swap them back cleanly. Test this code with strings containing multiple mixed citations.
    ```
* **Compulsory Verification Guardrail:** The validation routine must assert that running `deshield(shield(text))` matches the input text exactly. If any bracket or token alignment error occurs, the substitution map must rollback and re-parse the string.

#### Stage 9: LaTeX Formula & Mathematical Equation Masking Engine
* **Goal:** Extend your extraction patterns to protect inline and block math markup elements.
* **Prompt for Antigravity Agent:**
    ```text
    Extend your protection engines by coding 'backend/app/services/math_shield.py'. Develop matching routines for inline LaTeX mathematical syntax like '$E=mc^2$' and multi-line display equation code blocks delimited by double dollar brackets '$$...$$'. The function must swap out complex notation structures into safe lookup tokens like '__MATH_BLOCK_IDX__' prior to LLM processing. Write complete matching unit tests ensuring complex math structures with fractions or exponents parse cleanly without breaking text limits.
    ```
* **Compulsory Verification Guardrail:** The script must test nested expressions (e.g., fractional equations inside text). If the regex breaks math sequences into partial strings, the agent must update the matching regex to handle multi-line block configurations safely.

#### Stage 10: Adaptive Semantic Text Segmentation Chunker
* **Goal:** Build a semantic token-aware text slicing mechanism that breaks documents apart at logical paragraph boundaries.
* **Prompt for Antigravity Agent:**
    ```text
    Write an advanced semantic text processing block in 'backend/app/services/chunker.py'. Create a utility class 'SemanticChunker' that reads a document stream and chunks it into segments targeting roughly 500 words. The split boundaries must never clip a sentence in half; instead, prioritize slicing at double line breaks, paragraph marks, or punctuation symbols. Include a tracking mechanism that notes the original paragraph sequence indices. Create a validation test to verify sentence continuity across chunk splits.
    ```
* **Compulsory Verification Guardrail:** The testing script must pass text with variable lengths through the chunking block. If any block cuts off in the middle of a sentence, the chunker must shift its splitting index backward to the nearest punctuation mark.

#### Stage 11: Document Structural Reconstruction Mapper
* **Goal:** Develop an in-memory document tracker that maps processed text segments back to their original page layouts.
* **Prompt for Antigravity Agent:**
    ```text
    Code a structural layout manager in 'backend/app/services/layout_mapper.py'. Implement an object model 'DocumentStructureMap' that saves processing runs, tracking text chunk sequence hashes alongside their matching PDF page bounds and spatial coordinates. Ensure that modified text blocks can map back to their exact original layout positions. Write verification tests to confirm that every chunk matches an existing coordinate group.
    ```
* **Compulsory Verification Guardrail:** The mapping loop must double-check that the number of input chunks perfectly matches the number of generated output mappings. If there is a count mismatch, it must trigger a layout validation error and trace the missing index.

#### Stage 12: PDF Geometry Modification Detector
* **Goal:** Analyze font sizes and spacing to detect and prevent text from overflowing or breaking its container bounds.
* **Prompt for Antigravity Agent:**
    ```text
    Develop an overflow check module in 'backend/app/services/geometry_defender.py'. Write a function that estimates text size by evaluating string length against font sizes and bounding box parameters. If rewritten text exceeds the original bounding layout bounds by over 15%, throw an overflow alert so the system can adjust the formatting layout. Test this by passing overly long text blocks into constrained containers.
    ```
* **Compulsory Verification Guardrail:** If an overflow is detected during a test run, the script must calculate the required text compression or scale factor. It must confirm that the system can scale font sizes down proportionally to keep the text within its original container bounds.

#### Stage 13: Integrated Parsing Pipeline Integration Test
* **Goal:** Build a unified integration harness to run layout extraction, citation masking, and semantic chunking tasks sequentially.
* **Prompt for Antigravity Agent:**
    ```text
    Create an integration script 'backend/app/services/test_pipeline_integration.py'. Write an integration sequence that reads an input research paper PDF, maps out its layout geometry, runs the citation and math protection filters, and splits it into ordered text chunks. Print a complete verification summary displaying the total extracted chunks, masked token counts, and file structure validations to ensure data flows cleanly across modules.
    ```
* **Compulsory Verification Guardrail:** Run the complete test pipeline. If data loss occurs, if text strings become corrupted, or if coordinates drop offline during processing, the pipeline must throw a clear error, point out the failing component, and halt execution. The integration test must also confirm that the aggregated plain-text output is structurally complete and ready to be forwarded to the Global Context Extractor (Stage 14) — verifying total word count is above 500 words so the Master Summary generation will have sufficient input material.

---

### Phase 3: The Asynchronous Web & WebSocket Engine (Stages 15-21)


#### Stage 14: Global Context Injection — Master Summary Extractor
* **Goal:** Before chunk-level rewriting begins, send the entire parsed PDF plain text to a long-context model to generate a structured 200-word Master Summary containing the core thesis, methodology, and a 10-word technical glossary. Persist the summary to the database so every subsequent chunk prompt can inject it.
* **Prompt for Antigravity Agent:**
    ```text
    Develop a global context extraction service in 'backend/app/services/global_context_extractor.py'. Create a class 'GlobalContextExtractor' that accepts the full aggregated plain text of a parsed PDF document and the active run_id. Construct a specialized system prompt instructing a long-context model (targeting Gemini 1.5 Pro via the WaterfallRouter) to return a structured 200-word Master Summary formatted in three mandatory sections: (1) THESIS — the paper's core argument in 2-3 sentences, (2) METHODOLOGY — the primary technical approach in 2-3 sentences, and (3) GLOSSARY — exactly 10 domain-specific technical terms that must never be paraphrased or substituted during rewriting. Parse and validate the structured response to confirm all three sections are present. Persist the full Master Summary text to the 'master_summary' column of the active paper_run record in the database. Write a verification test that mocks the LLM call and confirms the summary is saved to and retrievable from the database.
    ```
* **Compulsory Verification Guardrail:** The extractor must validate that the returned Master Summary is between 150 and 250 words. If the LLM returns a response outside this range or omits any of the three required sections (THESIS, METHODOLOGY, GLOSSARY), the service must retry once with a stricter, structured prompt before accepting a fallback version. After saving, execute an explicit database query to confirm the master_summary column is non-NULL for the active run_id. If the column remains NULL after the write, abort the pipeline and surface a critical initialization error.

#### Stage 15: FastAPI Core App Configuration Instantiation
* **Goal:** Configure the primary ASGI application instance with CORS middleware and global error handlers.
* **Prompt for Antigravity Agent:**
    ```text
    Build the main entry point file 'backend/app/main.py'. Initialize a standard FastAPI instance, specifying an explicit title and API version. Apply robust CORS middleware rules allowing connections from localhost configurations. Register clear global exception handlers for unexpected internal server errors ('HTTP 500') and input data validation errors ('HTTP 422'). Write a test script to query application health status endpoints and verify successful initialization.
    ```
* **Compulsory Verification Guardrail:** The verification script must mock a broken request payload to trigger an intentional error state. If your error handling interceptors fail to capture the problem or return raw, unformatted stack traces to the caller, rewrite the exception mapping middleware.

#### Stage 16: Database Injection Dependency Middleware
* **Goal:** Build an asynchronous generator that injects clean, isolated database sessions into API routing scopes.
* **Prompt for Antigravity Agent:**
    ```text
    Develop dependency tracking middleware inside 'backend/app/api/deps.py'. Write an async generator function 'get_async_db()' that yields an active database session instance from your factory. Enclose the yield block inside a strict try-finally compound block to guarantee that sessions close cleanly, even if the request throws an unhandled exception. Write a unit verification function that creates a simulated session, verifies it is active, and confirms it closes cleanly.
    ```
* **Compulsory Verification Guardrail:** The testing framework must simulate an operational crash during database usage. It must confirm that the session cleanly rolls back uncommitted changes and closes the connection without leaving active connections open.

#### Stage 17: Asynchronous WebSocket Server Gateway Endpoint
* **Goal:** Establish an active connection route for WebSockets to handle real-time bi-directional messaging with the client interface.
* **Prompt for Antigravity Agent:**
    ```text
    Implement a WebSocket communication channel inside 'backend/app/api/websockets.py'. Create an active routing endpoint '/ws/status/{client_id}' that accepts incoming client requests, upgrades the communication protocol, and stores the active socket reference in a connection management dictionary. Include basic exception wrappers to catch connection drops and clean up dead references automatically. Write a mock client test connection script to verify smooth message loops.
    ```
* **Compulsory Verification Guardrail:** The mock script must initiate a connection, exchange messages, and drop the link unexpectedly. Your backend connection manager must detect the disconnected socket, close it cleanly, and remove the invalid connection reference without crashing the active server thread.

#### Stage 18: Live Status Event Broadcasting Dispatcher
* **Goal:** Build a centralized messaging manager to broadcast pipeline status updates and token metrics over active WebSockets.
* **Prompt for Antigravity Agent:**
    ```text
    Code a messaging controller class 'WebSocketManager' in 'backend/app/core/websocket_manager.py'. This manager must track active connection IDs and expose async utility methods like 'send_personal_message(msg, client_id)' and 'broadcast_global_message(msg)'. Message objects must follow a strict schema containing timestamp, message category, progress state, and active token updates. Write an execution test that broadcasts structured JSON messages to multiple mock listeners simultaneously.
    ```
* **Compulsory Verification Guardrail:** The broadcasting loop must catch failures when sending messages to stalled or dead connections. It must automatically disconnect bad sockets and ensure that communication issues with one client do not block deliveries to other active listeners.

#### Stage 19: PDF Upload API Core Processing Router
* **Goal:** Implement the primary multipart form endpoint to receive uploaded PDFs and initialize tracking records in the database.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the file upload processing engine 'backend/app/api/upload.py'. Create a FastAPI endpoint POST '/api/upload' that accepts a multipart file payload. Validate that the incoming file is a PDF. Generate a unique UUID for the run, save the binary document securely to your storage folder, parse the initial page counts, and log a new record into your database with an initial 'running' state. Write a mock upload test to verify this process end-to-end.
    ```
* **Compulsory Verification Guardrail:** The upload handler must reject oversized files or invalid, non-PDF file formats with a clear `400 Bad Request` error. It must confirm that the file stream is handled correctly in memory without leaking temporary disk fragments.

#### Stage 20: Live Token Budget State API Router
* **Goal:** Build a data tracking endpoint to query current token consumption metrics across all connected AI services.
* **Prompt for Antigravity Agent:**
    ```text
    Develop an information endpoint inside 'backend/app/api/stats.py'. Create an explicit path GET '/api/stats/tokens' that queries the database and extracts current quota metrics for Google, Groq, and DeepSeek. The response must calculate used vs. remaining token availability percentages. Write an automated execution verification step that seeds test values, calls the endpoint, and asserts that the calculated math balances perfectly.
    ```
* **Compulsory Verification Guardrail:** If the database queries return zero records, the tracking endpoint must fall back to default configurations instead of throwing a null error. Ensure the returned data matches your strict API schema definitions exactly.

#### Stage 21: Asynchronous Networking Health Integration Test
* **Goal:** Build a unified integration suite that exercises files, API routes, and active WebSocket connections simultaneously.
* **Prompt for Antigravity Agent:**
    ```text
    Assemble a system check suite inside 'backend/app/tests/test_async_network.py'. This script must use FastAPI's test client utilities to mock a full operational lifecycle: initialize the app, connect a mock WebSocket listener, send a multipart file payload, verify that the backend broadcasts appropriate tracking events over the socket link, and confirm that the Global Context Extractor is triggered post-upload — asserting that the master_summary column is non-NULL in the paper_runs record after the upload completes. Run this complete end-to-end integration check to confirm everything works smoothly.
    ```
* **Compulsory Verification Guardrail:** Execute the complete network test suite. If any race condition occurs between file writes and database updates, or if the WebSocket drops messages under load, trace the execution thread, fix the synchronization parameters, and re-run the tests.

---

### Phase 4: The Waterfall Multi-API Router (Stages 22-28)

#### Stage 22: Base Model Abstract API Integration Framework
* **Goal:** Code the parent abstract class structure defining standard execution patterns for external language model calls.
* **Prompt for Antigravity Agent:**
    ```text
    Create an abstract base architecture in 'backend/app/services/base_llm.py'. Define an explicit abstract interface class 'BaseLLMProvider' using Python's 'abc' module. Declare an async abstract method 'execute_text_rewrite(prompt, context_chunk)' that returns a string. Include a standard parsing function that processes model responses and extracts the clean text body. Write a test mock to verify your class definitions and abstract constraints work as intended.
    ```
* **Compulsory Verification Guardrail:** The validation suite must verify that attempting to initialize the abstract interface class directly throws an expected `TypeError`. Ensure all derived methods enforce proper keyword type constraints.

#### Stage 23: Google Gemini Free-Tier Client Connector
* **Goal:** Build the concrete service class to interface with Google AI Studio's Gemini models using their free developer tier.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the Gemini integration client inside 'backend/app/services/google_provider.py'. Create a concrete class 'GoogleGeminiProvider' that inherits from your abstract base class. Configure it to route payloads asynchronously to Google's API endpoint, targeting 'gemini-1.5-flash'. Read settings dynamically using your core configuration modules. Include basic error mapping logic to catch invalid keys or empty text responses, and write a verification function to mock a successful API transaction.
    ```
* **Compulsory Verification Guardrail:** The integration client must catch rate limit errors (`429`) and connection drops (`503`) cleanly, raising a specialized system exception (`ExternalApiThrottleException`) so the master router can handle the failover smoothly.

#### Stage 24: Groq Cloud LPU Client Connector
* **Goal:** Implement the concrete service connector for the Groq Cloud platform to utilize fast open-source models like Llama 3.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the Groq execution client inside 'backend/app/services/groq_provider.py'. Create a concrete class 'GroqProvider' derived from your abstract base. Use aiohttp to connect to Groq's endpoint, targeting 'llama-3.1-70b-versatile'. Ensure the client passes your system prompt parameters cleanly. Code a unit testing module that verifies prompt payloads match Groq's chat completion schema formatting exactly.
    ```
* **Compulsory Verification Guardrail:** The client must extract token metrics (`prompt_tokens`, `completion_tokens`) directly from the API response payload. If the response fields are missing or unexpected, default to fallback estimations to prevent parsing failures.

#### Stage 25: DeepSeek Deep Reasoning Client Connector
* **Goal:** Build the concrete service connector to interface with DeepSeek's API for complex reasoning models like DeepSeek-R1.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the DeepSeek interface connector inside 'backend/app/services/deepseek_provider.py'. Create a class 'DeepSeekProvider' to route requests to the DeepSeek endpoint, targeting 'deepseek-reasoning' or 'deepseek-chat'. Configure the JSON parser to strip out internal chain-of-thought blocks if present, returning only the final rewritten output text. Write a verification script to test response parsing against mock data.
    ```
* **Compulsory Verification Guardrail:** The deep reasoning parser must cleanly handle long response strings without cutting off mid-text. Ensure it isolates reasoning paths and returns only clean text to the caller.

#### Stage 26: Master API Waterfall Failover Router Controller
* **Goal:** Code the central controller class that coordinates your API providers into an automated failover sequence.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the primary routing manager inside 'backend/app/services/api_router.py'. Create a class 'WaterfallRouter' that holds an ordered collection of your provider clients (Gemini Flash, Gemini Pro, Groq, DeepSeek). Implement an async method 'rewrite_chunk_with_failover(prompt, text)' that loops through providers sequentially. If a provider raises an exception or hits a rate limit, catch the error, broadcast an event to your WebSocket listeners, and automatically try the next provider in the chain. Test this behavior by intentionally mocking a failure on the primary provider.
    ```
* **Compulsory Verification Guardrail:** The router must monitor token usage quotas stored in your database. If a provider's daily token budget is exhausted, skip that provider entirely and route requests directly to the next available engine in the waterfall.

#### Stage 27: Dynamic System Prompt Orchestration Compiler
* **Goal:** Design an engineering framework that compiles text chunks into optimized prompts that instruct the LLM to maximize text variance.
* **Prompt for Antigravity Agent:**
    ```text
    Create a prompt compilation library in 'backend/app/services/prompt_factory.py'. Write a class 'PromptFactory' that builds system instructions. The factory must accept the active run_id and retrieve the Master Summary from the 'master_summary' column of the paper_runs table. Prepend this Master Summary as a CONTEXT BLOCK at the very top of every system prompt, with an explicit instruction to: (a) preserve all 10 technical glossary terms from the GLOSSARY section verbatim, (b) maintain thematic consistency with the THESIS section, and (c) not deviate from the METHODOLOGY described. Following the context block, the prompt must explicitly command the model to maximize text perplexity and burstiness metrics, eliminate common AI transition words, use active voice structures, and preserve all structural token placeholders exactly. Write a verification test to ensure the Master Summary context block is present and correctly prepended in the compiled prompt.
    ```
* **Compulsory Verification Guardrail:** The factory must validate that the final prompt string contains: (1) the Master Summary context block retrieved from the database, (2) the required protection tokens (`__CITATION_IDX__`, `__MATH_BLOCK_IDX__`). If the Master Summary is NULL or empty in the database, the factory must raise a MissingSummaryError and halt chunk processing for that run. If citation or math placeholders are missing or corrupted, throw an error to prevent data loss before sending the prompt to the API.

#### Stage 28: Multi-Provider Failover Integration Test
* **Goal:** Execute a comprehensive integration test that simulates API rate limits and verifies successful failovers across your providers.
* **Prompt for Antigravity Agent:**
    ```text
    Develop a test suite inside 'backend/app/tests/test_waterfall_robustness.py'. Mock your API clients so that the first two providers return immediate connection errors or rate-limit exceptions, while the third provider returns a valid text response. Run your failover router through this scenario and assert that it handles the errors silently, logs the events to the database, and returns the successful result smoothly.
    ```
* **Compulsory Verification Guardrail:** The test runner must confirm that all token logs are updated correctly in the database throughout the failover process. If metrics fail to record, or if errors bubble up and crash the execution thread, refactor your exception handling blocks.

---

### Phase 5: Local Adversarial Testing Tier (Stages 29-35)

#### Stage 29: Local AI Detection Server Instantiation
* **Goal:** Create an isolated local classification server using Hugging Face transformers to score text blocks for AI characteristics.
* **Prompt for Antigravity Agent:**
    ```text
    Develop a local text scoring classifier in 'backend/app/services/local_detector.py'. Implement a class 'LocalAdversarialDetector' that loads the 'roberta-base-openai-detector' model into memory using standard Hugging Face pipelines. Configure execution to default to CPU mode for maximum portability. Write an async method 'calculate_ai_probability(text)' that returns a clean percentage score between 0% and 100%. Test the engine with sample text to verify score returns.
    ```
* **Compulsory Verification Guardrail:** The classification script must check system memory levels before loading the model weights. If host memory allocation fails or is restricted, initialize a smaller, quantized model version to prevent system resource crashes.

#### Stage 30: Local vs. Serverless Alternative Execution Router
* **Goal:** Build a failover mechanism for the detector that switches to Hugging Face's serverless inference API if local hardware resources are limited.
* **Prompt for Antigravity Agent:**
    ```text
    Develop a fallback system for your detector inside 'backend/app/services/detector_fallback.py'. Modify your detector class to implement a fallback check. If the local machine lacks sufficient RAM or a compatible CPU execution layer, route scoring requests to Hugging Face's serverless inference endpoint using aiohttp. Ensure both processing paths return consistent data schemas, and write a test to mock an API fallback scenario.
    ```
* **Compulsory Verification Guardrail:** The API client must include a timeout constraint of 8 seconds when calling the serverless endpoint. If the network call times out, fall back to a basic statistical analyzer module to calculate scores and keep the app running.

#### Stage 31: Text Burstiness & Complexity Math Processor
* **Goal:** Code a quick statistical processor to calculate structural variance metrics across text strings using standard text metrics.
* **Prompt for Antigravity Agent:**
    ```text
    Create a statistical text processing module in 'backend/app/services/metrics_calculator.py'. Write a function that tokenizes incoming text into sentences and counts word frequencies. Calculate sentence length standard deviations and vocabulary variation ratios to determine structural complexity metrics. Ensure the function handles edge cases gracefully, such as empty inputs or single-sentence blocks, and write unit tests to confirm the math outputs.
    ```
* **Compulsory Verification Guardrail:** The calculation formulas must protect against division-by-zero errors when processing empty text blocks or short strings. If an anomaly occurs, return zeroed metrics safely.

#### Stage 32: The Iterative Feedback Control Loop
* **Goal:** Build the main feedback engine that runs text through the rewriting and scoring loop until it passes humanization thresholds.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the core loops inside 'backend/app/services/loop_controller.py'. Create a coordinator class 'FeedbackLoopController' that links your rewriting router and adversarial detector. Write an async method that rewrites a text chunk, scores it, and loops up to 3 times if the AI score is above 15%. If it passes or hits the iteration cap, save the best-performing text version and proceed. Test this with a mock sequence to confirm looping behavior.
    ```
* **Compulsory Verification Guardrail:** The loop controller must track iteration counts. If a chunk hits the maximum loop limit without passing the threshold, log the event, skip further loops, and save the version with the lowest AI score to prevent infinite execution loops.

#### Stage 33: Mathematical Convergence Diagnostic Analyzer
* **Goal:** Build a diagnostic tool to analyze how effectively the text score improves across successive loop iterations.
* **Prompt for Antigravity Agent:**
    ```text
    Code a diagnostic system in 'backend/app/services/convergence_analyzer.py'. Write a tool that tracks historical scoring updates across iterations. If scores stall or fail to improve between loops, append strict corrective instructions to the next prompt, such as demanding more aggressive changes or vocabulary updates. Write verification tests to confirm prompt adjustments are made correctly.
    ```
* **Compulsory Verification Guardrail:** If text changes begin to degrade or loop efficiency drops below a set performance threshold, stop looping immediately and output the current best text variant to protect token budgets.

#### Stage 34: Multi-Threaded Batch Processing Manager
* **Goal:** Build an asynchronous batch manager that runs multiple text chunks through the humanizer loop concurrently to maximize throughput.
* **Prompt for Antigravity Agent:**
    ```text
    Develop an asynchronous batch processing engine inside 'backend/app/services/batch_manager.py'. Create a manager function that takes an array of text chunks and runs them through your processing pipeline concurrently using 'asyncio.gather'. Limit concurrent execution to 3 workers to respect API rate limits. Write an integration test to confirm that chunks are processed correctly and finish without dropping records.
    ```
* **Compulsory Verification Guardrail:** The batch runner must handle individual chunk failures gracefully. If a single chunk crashes during processing, isolate the failure, log the error context, and ensure all other parallel operations continue running normally.

#### Stage 35: Local Adversarial Tier Validation Test
* **Goal:** Run an end-to-end integration test validating the entire text rewriting, scoring, and feedback loop sequence.
* **Prompt for Antigravity Agent:**
    ```text
    Create an integrated pipeline validation test file 'backend/app/tests/test_adversarial_tier.py'. Script a full execution sequence that feeds a robotic, AI-generated text block into the loop controller, verifies that the detector flags it, triggers a rewrite loop, and successfully outputs humanized text with a lower AI score. The test must additionally assert that the PromptFactory correctly injects a mock Master Summary context block into every prompt sent to the rewriting engine, and that the GLOSSARY terms from the summary appear preserved in the final humanized output. Ensure all assertions pass cleanly.
    ```
* **Compulsory Verification Guardrail:** Run the complete adversarial test suite. If the loop controller loses text data or fails to update progress states over the WebSocket link during execution, refactor the synchronization handlers and rerun the tests.

---

### Phase 6: Document Assembly & Layout Reconstruction Tier (Stages 36-42)

#### Stage 36: Layout Coordinate Matching Logic
* **Goal:** Map your humanized text blocks back to the original document structure by aligning them with their saved paragraph layout indices.
* **Prompt for Antigravity Agent:**
    ```text
    Develop structural mapping utilities inside 'backend/app/services/alignment_engine.py'. Create a data engine class 'LayoutAlignmentEngine' that takes processed text chunks and aligns them with their original document positions using saved sequence numbers. Ensure that text sections match their corresponding layout containers exactly, and write an automated verification test to validate index integrity.
    ```
* **Compulsory Verification Guardrail:** The alignment engine must verify that no sequence indices are missing or duplicate. If an index error occurs, stop assembly immediately, log the missing chunk data, and raise an execution error to prevent document corruption.

#### Stage 37: Canvas Layout Reconstruction Engine
* **Goal:** Create a PDF generation class using ReportLab to draw your humanized text chunks onto a new document canvas layer.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the canvas generation code in 'backend/app/services/canvas_builder.py'. Create a PDF rendering coordinator class 'CanvasReconstructor' using ReportLab's canvas utilities. Write a method that reads your layout maps and draws text strings onto a new document canvas using the exact coordinate parameters ($X, Y$), matching font styles, and sizing rules extracted from the original PDF. Code a basic structural layout test to verify rendering accuracy.
    ```
* **Compulsory Verification Guardrail:** The canvas builder must parse text strings to ensure all protected formatting placeholders are unmasked and restored correctly. If raw placeholder tokens remain in the text, halt rendering immediately.

#### Stage 38: Text Font Unmasking & Deshielding Service
* **Goal:** Re-inject your original, protected math formulas and inline citations back into the final humanized text strings before rendering.
* **Prompt for Antigravity Agent:**
    ```text
    Develop a token restoring module inside 'backend/app/services/token_restorer.py'. Write a utility function 'restore_shielded_tokens(text, translation_dict)' that parses text strings, finds placeholders like '__CITATION_IDX__' or '__MATH_BLOCK_IDX__', and replaces them with their original math markup and citation strings. Write complete unit tests to verify that restoring operations match your original inputs exactly.
    ```
* **Compulsory Verification Guardrail:** The replacement loop must confirm that every placeholder token is successfully swapped out. If any placeholder strings remain in the text after processing, trigger an unmasking compilation error.

#### Stage 39: Multi-Line Document Flow Optimizer
* **Goal:** Implement paragraph text-wrapping logic to dynamically adjust spacing and prevent rewritten text from overlapping layout boundaries.
* **Prompt for Antigravity Agent:**
    ```text
    Develop text-wrapping adjustments inside 'backend/app/services/flow_optimizer.py'. Create an optimization module that calculates text lengths against original block boundaries. If humanized text runs longer than the original text block, dynamically adjust line spacing and font sizes down by up to 10% to fit the text within the container. Test this behavior with long strings to verify scaling accuracy.
    ```
* **Compulsory Verification Guardrail:** The spacing adjustments must never shrink font sizes below a readable limit of 7 points. If a block still overflows after scaling, split the overflow text cleanly and append it as a trailing block to maintain readability.

#### Stage 40: Structural PDF Layout Merger
* **Goal:** Merge your newly drawn text canvas layers with the original PDF background graphics to keep diagrams and charts intact.
* **Prompt for Antigravity Agent:**
    ```text
    Develop document blending layers inside 'backend/app/services/pdf_merger.py'. Write a service function that takes the newly generated text canvas layer and overlays it onto the original background template document page by page using PyMuPDF. This keeps all non-text structural elements like charts and tables completely intact. Write a test to confirm the merged page counts are correct.
    ```
* **Compulsory Verification Guardrail:** The merger must verify that the page counts of the background template and the text canvas layer match exactly. If there is a page count mismatch, stop execution immediately to prevent layout corruption.

#### Stage 41: Multi-Page Processing Document Stream Optimizer
* **Goal:** Optimize file exports by cleaning up temporary render artifacts and managing systemic disk usage during file production.
* **Prompt for Antigravity Agent:**
    ```text
    Develop file cleanup routines inside 'backend/app/services/file_janitor.py'. Write a file management class that cleans up temporary canvas fragments, scratch folders, and intermediate build documents created during PDF assembly. Ensure it releases file locks cleanly on the export directory, and write verification tests to confirm files are deleted successfully.
    ```
* **Compulsory Verification Guardrail:** The cleanup service must never delete the original uploaded document or the final exported file. Run explicit path checks to confirm only temporary file assets are removed.

#### Stage 42: Assembly Pipeline Integration Test
* **Goal:** Run a complete integration test validating the entire PDF extraction, token unmasking, canvas drawing, and layout reconstruction sequence.
* **Prompt for Antigravity Agent:**
    ```text
    Create an integration testing script 'backend/app/tests/test_assembly_pipeline.py'. Build a test sequence that takes an extracted layout map, runs token unmasking to restore citations, draws the text onto a canvas layer using coordinate bounds, and merges it into a finished PDF file. Verify that the output document is scannable and layout-compliant.
    ```
* **Compulsory Verification Guardrail:** Run the complete assembly validation suite. If text alignment shifts out of bounds, or if the exported PDF file is corrupted, trace the rendering loop, fix the canvas coordinate parameters, and rerun the tests.

---

### Phase 7: Production-Grade Frontend Application (Stages 43-48)

#### Stage 43: Modern Base Application Scaffold Layout
* **Goal:** Build the primary responsive user interface layout with Tailwind CSS, featuring sidebar panels and file upload terminals.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the core UI layout file 'frontend/index.html'. Design a responsive dashboard using Tailwind CSS with a dark theme. Create a sidebar panel to show real-time API connection indicators and a main control layout featuring a drag-and-drop file upload terminal. Include necessary font styles and UI framework dependencies locally, and run a layout check to ensure it displays correctly.
    ```
* **Compulsory Verification Guardrail:** The interface layout must render cleanly across both desktop and mobile viewports. If layout elements overlap or break responsiveness on smaller screens, fix the responsive utility classes.

#### Stage 44: JavaScript WebSocket Event Processing Controller
* **Goal:** Implement the primary frontend communication manager to open WebSockets and handle real-time status updates from the backend.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the frontend communication script 'frontend/js/websocket_client.js'. Create a JavaScript class 'WebSocketClient' that opens a WebSocket link to the backend server. Code message handling routines to parse incoming JSON packets and route progress metrics and state changes to your UI components. Write a test suite to verify connection handling and automated reconnection logic.
    ```
* **Compulsory Verification Guardrail:** The connection client must handle network drops gracefully. It must implement an exponential backoff retry strategy to reconnect automatically without freezing the user interface or losing session state.

#### Stage 45: Real-Time Node Map Visualization Panel
* **Goal:** Create a visual layout map component that lights up and animates nodes dynamically as chunks process through the pipeline.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the pipeline visualization script 'frontend/js/pipeline_view.js'. Create a visual node component that maps out the humanizer pipeline stages (Upload -> Chunking -> Rewriting -> Detection -> Assembly). Write update methods to dynamically highlight active nodes and animate loop connections when a chunk is sent back for rewriting based on incoming WebSocket events.
    ```
* **Compulsory Verification Guardrail:** The visualization panel must handle rapid event updates gracefully without causing browser rendering lag. If events arrive faster than the UI animations can render, batch updates together to maintain smooth performance.

#### Stage 46: Live Token Burn Dashboard Component
* **Goal:** Implement an interactive metrics panel displaying live data usage and available token balances for each provider.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the metrics panel interface component 'frontend/js/token_dashboard.js'. Create an interactive dashboard section that displays token utilization metrics for Google, Groq, and DeepSeek. Implement animated status rings or progress bars that update dynamically when token consumption logs are received over the WebSocket link.
    ```
* **Compulsory Verification Guardrail:** The metrics display must handle empty initial token logs safely without showing broken values or NaN errors. Initialize all counters to zero and ensure values transition smoothly as data arrives.

#### Stage 47: Native Browser Download Action Interface
* **Goal:** Build the interface components to display file download links and process file exports once the backend complete message is received.
* **Prompt for Antigravity Agent:**
    ```text
    Develop the download management script 'frontend/js/download_manager.js'. Create a UI panel that appears automatically when the backend announces a document run has finished successfully. Include an action button that opens the file export route to download the completed PDF natively in the browser, and verify file transfer handling.
    ```
* **Compulsory Verification Guardrail:** The download action must handle file system errors gracefully. If the export file is missing or returns a server error, intercept the failure, display an error notification to the user, and keep the application state responsive.

#### Stage 48: Integrated Frontend Interface Integration Test
* **Goal:** Run a comprehensive frontend integration test to verify message routing, panel animations, and state transitions across your components.
* **Prompt for Antigravity Agent:**
    ```text
    Create a frontend test wrapper file 'frontend/js/test_frontend_integration.js'. Write a testing routine that mocks a complete series of incoming backend WebSocket events, verifies that node panels update and animate correctly, and confirms that the token meters and final download actions transition states smoothly.
    ```
* **Compulsory Verification Guardrail:** Run the complete frontend validation suite. If any UI updates fail to render, or if component state synchronization falls out of step under rapid messaging streams, fix the state management handlers.

---

### Phase 8: E2E Verification & Deployment Orchestration (Stages 49-51)

#### Stage 49: Unified System Application Bootstrapper
* **Goal:** Write a single entry-point execution script to initialize the database, verify folders, and boot the web application server safely.
* **Prompt for Antigravity Agent:**
    ```text
    Develop a unified system bootloader file 'main.py' in the root directory. Write an execution routine that creates necessary workspace folders, checks for required configuration variables in '.env', runs database setup and seeding scripts, and starts the FastAPI application server via Uvicorn on port 8000. Ensure it includes robust error logs to capture initialization errors.
    ```
* **Compulsory Verification Guardrail:** The bootloader must verify port availability before starting the server. If port 8000 is occupied, intercept the error, log a clear warning message, and scan for the next available port to prevent startup crashes.

#### Stage 50: Full End-to-End System Integration Test Suite
* **Goal:** Run a comprehensive end-to-end integration test verifying file ingestion, multi-api failover, loop processing, and document assembly.
* **Prompt for Antigravity Agent:**
    ```text
    Create a complete end-to-end integration suite 'backend/app/tests/test_e2e_main.py'. Write a testing script that uses FastAPI test utilities to simulate a full user journey: upload a sample academic PDF, mock API failovers across providers, run through the adversarial scoring loop, verify layout preservation, and confirm the final generated file exports successfully.
    ```
* **Compulsory Verification Guardrail:** The end-to-end test suite must run completely without human intervention. If any component timeouts, race conditions, or database deadlocks occur under full integration simulation, fix the system hooks and rerun the tests.

#### Stage 51: System Pre-Flight Checklist Optimization
* **Goal:** Build a production pre-flight checking engine to evaluate global software health, confirm file permissions, and verify API connectivity.
* **Prompt for Antigravity Agent:**
    ```text
    Develop a system pre-flight check utility 'preflight.py' in the root folder. Write a script that scans the local runtime environment: verifies write permissions on the storage directories, checks the local SQLite database schema integrity, tests network latency to Hugging Face and external API endpoints, and prints a formatted system health card to the console.
    ```
* **Compulsory Verification Guardrail:** The preflight check must clearly output either a green light status or a descriptive error list pointing out missing environment variables or network blocks. It must block the main application from booting if critical configuration errors are found.

---

### How to Execute This in Antigravity

Open your Antigravity Editor environment, enter the **Manager view**, spawn an advanced software engineering agent, and feed it **Stage 1**. Once it confirms execution and passes the compulsory verification guardrail, paste the next stage. This step-by-step approach ensures you build a highly reliable application perfectly tailored for your research paper within your timeline.