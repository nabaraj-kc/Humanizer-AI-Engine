/**
 * frontend/js/app.js
 * ==================
 * Master Frontend Application Orchestrator Controller.
 * Binds UI drag-drop zones, WebSocket connection status, progress map visualizer,
 * API token quota gauges, and documents history panel together.
 */

class HumanizerAppController {
    constructor() {
        // Generate a random client UUID session token
        this.clientId = this.generateUUID();
        this.isProcessing = false;
        this.lastProgressState = 'idle';

        // Resolve backend hosts dynamically to support local serve port 8080 -> API port 8000 mapping
        const backendHost = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
            ? `${window.location.hostname}:8000`
            : window.location.host;

        this.backendBaseUrl = `${window.location.protocol}//${backendHost}`;
        
        // Cache DOM elements
        this.uploadZone = document.getElementById('pdf-upload-zone');
        this.fileInput = document.getElementById('pdf-file-input');
        this.uploadIcon = document.getElementById('upload-icon-container');
        this.uploadTitle = document.getElementById('upload-title');
        this.uploadDesc = document.getElementById('upload-desc');
        this.uploadLoadingText = document.getElementById('upload-loading-text');

        this.wsBulb = document.getElementById('ws-status-bulb');
        this.wsText = document.getElementById('ws-status-text');

        this.warningBox = document.getElementById('alert-warning-box');
        this.warningText = document.getElementById('alert-warning-text');
        this.statsText = document.getElementById('processing-stats-text');

        this.runsTableBody = document.getElementById('runs-table-body');
        this.refreshRunsBtn = document.getElementById('refresh-runs-btn');
        this.deleteAllBtn = document.getElementById('delete-all-btn');

        // Text Mode elements
        this.tabPdfBtn = document.getElementById('tab-pdf-btn');
        this.tabTextBtn = document.getElementById('tab-text-btn');
        this.panelText = document.getElementById('panel-text');
        this.textTitleInput = document.getElementById('text-title-input');
        this.textInput = document.getElementById('text-input');
        this.textCharCount = document.getElementById('text-char-count');
        this.clearTextBtn = document.getElementById('clear-text-btn');
        this.humanizeTextBtn = document.getElementById('humanize-text-btn');
        this.textResultPanel = document.getElementById('text-result-panel');
        this.copyResultBtn = document.getElementById('copy-result-btn');
        this.downloadTextResultBtn = document.getElementById('download-text-result-btn');
        this.newTextBtn = document.getElementById('new-text-btn');
        this.textResult = document.getElementById('text-result');

        // Initial instantiate helper objects
        this.wsClient = new window.WebSocketClient(this.clientId, backendHost);
        this.pipelineView = new window.PipelineNodeView('svg-visualization-container');

        // Bind core handlers
        this.bindEvents();

        // Load initial quota details
        this.fetchTokenStats();

        // Load documents history
        this.fetchRuns();

        // Connect status channel
        this.wsClient.connect();
    }

    /**
     * Bind listeners to UI interactions
     */
    bindEvents() {
        // WebSocket callbacks
        this.wsClient.onStatusChangeCallback = (status) => this.handleWSStatusChange(status);
        this.wsClient.onMessageCallback = (data) => this.handleWSMessage(data);

        // Click on drag-drop zone forwards to hidden file input
        this.uploadZone.addEventListener('click', () => {
            if (this.isProcessing) {
                this.showWarning("An active processing run is in progress. Double upload submittals are rejected.");
                return;
            }
            if (document.getElementById('download-doc-btn')) {
                return;
            }
            this.fileInput.click();
        });

        // File input changes
        this.fileInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                this.handleFileSelected(e.target.files[0]);
            }
        });

        // Drag and drop event listeners
        ['dragenter', 'dragover'].forEach(eventName => {
            this.uploadZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (!this.isProcessing) {
                    this.uploadZone.classList.add('dragover');
                }
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            this.uploadZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.uploadZone.classList.remove('dragover');
            }, false);
        });

        this.uploadZone.addEventListener('drop', (e) => {
            if (this.isProcessing) {
                this.showWarning("An active processing run is in progress. Double upload submittals are rejected.");
                return;
            }
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files && files.length > 0) {
                this.handleFileSelected(files[0]);
            }
        }, false);

        // Text paste area listeners
        if (this.textInput) {
            this.textInput.addEventListener('input', () => {
                // Autoexpand text area size dynamically
                this.textInput.style.height = 'auto';
                this.textInput.style.height = `${this.textInput.scrollHeight}px`;

                // Update character counter
                const len = this.textInput.value.length;
                this.textCharCount.textContent = `${len.toLocaleString()} / 60,000`;

                // Set semantic colors based on sizes
                this.textCharCount.className = 'text-xs font-mono';
                if (len <= 50000) {
                    this.textCharCount.classList.add('char-ok');
                } else if (len <= 60000) {
                    this.textCharCount.classList.add('char-warn');
                } else {
                    this.textCharCount.classList.add('char-limit');
                }
            });
        }

        // Paste Text panel buttons hooks
        if (this.clearTextBtn) {
            this.clearTextBtn.addEventListener('click', () => this.clearText());
        }

        if (this.humanizeTextBtn) {
            this.humanizeTextBtn.addEventListener('click', () => this.humanizeText());
        }

        if (this.copyResultBtn) {
            this.copyResultBtn.addEventListener('click', () => this.copyResult());
        }

        if (this.downloadTextResultBtn) {
            this.downloadTextResultBtn.addEventListener('click', () => {
                if (this.activeRunId) {
                    window.location.href = `${this.backendBaseUrl}/api/download/${this.activeRunId}`;
                }
            });
        }

        if (this.newTextBtn) {
            this.newTextBtn.addEventListener('click', () => this.resetTextPanel());
        }

        // Refresh runs button
        if (this.refreshRunsBtn) {
            this.refreshRunsBtn.addEventListener('click', () => {
                this.fetchRuns();
            });
        }

        // Delete all history runs button
        if (this.deleteAllBtn) {
            this.deleteAllBtn.addEventListener('click', () => {
                this.deleteAllRuns();
            });
        }
    }

    /**
     * Handle tab switching logic
     * @param {string} mode 'pdf' | 'text'
     */
    switchTab(mode) {
        if (this.isProcessing) {
            this.showWarning("An active processing run is in progress. Tab switching is locked.");
            return;
        }

        this.hideWarning();

        if (mode === 'pdf') {
            this.tabPdfBtn.classList.add('tab-active');
            this.tabPdfBtn.classList.remove('bg-slate-800/20', 'text-slate-400');
            this.tabPdfBtn.classList.add('bg-slate-800/40', 'text-slate-300');

            this.tabTextBtn.classList.remove('tab-active');
            this.tabTextBtn.classList.remove('bg-slate-800/40', 'text-slate-300');
            this.tabTextBtn.classList.add('bg-slate-800/20', 'text-slate-400');

            this.uploadZone.classList.remove('hidden');
            this.panelText.classList.add('hidden');
        } else {
            this.tabTextBtn.classList.add('tab-active');
            this.tabTextBtn.classList.remove('bg-slate-800/20', 'text-slate-400');
            this.tabTextBtn.classList.add('bg-slate-800/40', 'text-slate-300');

            this.tabPdfBtn.classList.remove('tab-active');
            this.tabPdfBtn.classList.remove('bg-slate-800/40', 'text-slate-300');
            this.tabPdfBtn.classList.add('bg-slate-800/20', 'text-slate-400');

            this.panelText.classList.remove('hidden');
            this.uploadZone.classList.add('hidden');
            
            // Re-trigger textarea height fit on initial switch display
            setTimeout(() => {
                if (this.textInput) {
                    this.textInput.dispatchEvent(new Event('input'));
                }
            }, 50);
        }
    }

    /**
     * Clear textarea content and reset display fields
     */
    clearText() {
        if (this.textInput) {
            this.textInput.value = '';
            this.textInput.dispatchEvent(new Event('input'));
        }
    }

    /**
     * Handle incoming selected file
     * @param {File} file PDF document
     */
    handleFileSelected(file) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            this.showWarning("Only PDF documents are supported for processing.");
            return;
        }

        this.isProcessing = true;
        this.hideWarning();
        this.setUploadLock(true);

        this.pipelineView.updateState('parsing');
        this.statsText.textContent = 'Parsing...';

        this.uploadFile(file);
    }

    /**
     * POST file to FastAPI /api/upload endpoint
     * @param {File} file 
     */
    async uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch(`${this.backendBaseUrl}/api/upload`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Upload failed.');
            }

            const result = await response.json();
            this.activeRunId = result.run_id; // Save run_id for download
            console.log('Upload successfully initialized:', result);
            this.statsText.textContent = 'Uploading successful. Waiting for pipeline...';
            
            // Refresh runs table to show new in-progress run
            this.fetchRuns();
            
            // Note: background pipeline execution will trigger WebSocket progress events
        } catch (err) {
            console.error('Upload error:', err);
            this.showWarning(`Processing initialization failed: ${err.message}`);
            this.resetPipeline('failed');
        }
    }

    /**
     * Send pasted text to humanizer endpoint
     */
    async humanizeText() {
        if (this.isProcessing) {
            this.showWarning("An active processing run is in progress. Double submittals are rejected.");
            return;
        }

        const val = this.textInput.value.trim();
        const customTitle = this.textTitleInput ? this.textTitleInput.value.trim() : "";
        if (!val) {
            this.showWarning("Please paste some text content to humanize.");
            return;
        }

        if (val.length > 60000) {
            this.showWarning("Input text exceeds the maximum character capacity of 60,000.");
            return;
        }

        this.isProcessing = true;
        this.hideWarning();
        this.setTextInputLock(true);
        if (this.textResultPanel) {
            this.textResultPanel.classList.add('hidden');
        }

        this.pipelineView.updateState('parsing');
        this.statsText.textContent = 'Parsing...';

        try {
            const response = await fetch(`${this.backendBaseUrl}/api/humanize-text`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: val, name: customTitle })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Text processing initialization failed.');
            }

            const result = await response.json();
            this.activeRunId = result.run_id;
            console.log('Text humanizer initialized:', result);
            this.statsText.textContent = 'Parsing success. Rewriting blocks...';

            this.fetchRuns();
        } catch (err) {
            console.error('Text humanize error:', err);
            this.showWarning(`Processing initialization failed: ${err.message}`);
            this.resetPipeline('failed');
            this.setTextInputLock(false);
        }
    }

    /**
     * Retrieve inline text results from completed run
     * @param {string} runId 
     */
    async fetchTextResult(runId) {
        try {
            const response = await fetch(`${this.backendBaseUrl}/api/result/${runId}`);
            if (!response.ok) throw new Error("Could not download text content");

            const data = await response.json();
            if (data.status === 'success' && data.content) {
                if (this.textResult && this.textResultPanel) {
                    this.textResult.value = data.content;
                    this.textResultPanel.classList.remove('hidden');
                    
                    // Autoexpand output result textarea size
                    this.textResult.style.height = 'auto';
                    this.textResult.style.height = `${this.textResult.scrollHeight}px`;
                }
            }
        } catch (err) {
            console.error("Fetch result content failed:", err);
            this.showWarning("Completed humanized text result retrieval failed.");
        }
    }

    /**
     * Copy humanized output content to clipboard
     */
    copyResult() {
        if (this.textResult && this.textResult.value) {
            navigator.clipboard.writeText(this.textResult.value).then(() => {
                const prev = this.copyResultBtn.innerHTML;
                this.copyResultBtn.innerHTML = '<span>📋</span><span>Copied!</span>';
                setTimeout(() => {
                    this.copyResultBtn.innerHTML = prev;
                }, 2000);
            }).catch(e => {
                console.error("Clipboard copy failed:", e);
                this.showWarning("Copy to clipboard permission rejected by browser.");
            });
        }
    }

    /**
     * Reset text panel controls and restore default view
     */
    resetTextPanel() {
        if (this.textResultPanel) {
            this.textResultPanel.classList.add('hidden');
        }
        if (this.textResult) {
            this.textResult.value = '';
        }
        this.setTextInputLock(false);
        this.clearText();
        this.restoreUploadZone();
    }

    /**
     * Query API Token usage states from server
     */
    async fetchTokenStats() {
        try {
            const response = await fetch(`${this.backendBaseUrl}/api/stats/tokens`);
            if (!response.ok) throw new Error("Stats fetch failed");
            
            const data = await response.json();
            if (data.status === 'success' && data.providers) {
                this.updateQuotaBars(data.providers);
            }
        } catch (err) {
            console.warn("Could not fetch token statistics from backend:", err);
        }
    }

    /**
     * Fetch and render the documents history from /api/runs
     */
    async fetchRuns() {
        if (!this.runsTableBody) return;

        try {
            const response = await fetch(`${this.backendBaseUrl}/api/runs`);
            if (!response.ok) throw new Error("Runs fetch failed");
            
            const data = await response.json();
            this.renderRunsTable(data.runs || []);
        } catch (err) {
            console.warn("Could not fetch runs list from backend:", err);
            this.runsTableBody.innerHTML = `
                <tr>
                    <td colspan="6" class="px-4 py-8 text-center text-slate-500">
                        <div class="flex flex-col items-center space-y-2">
                            <span class="text-xl">⚠️</span>
                            <span>Could not load documents. Backend may be unavailable.</span>
                        </div>
                    </td>
                </tr>`;
        }
    }

    /**
     * Render the runs history table with the provided runs list
     * @param {Array} runs 
     */
    renderRunsTable(runs) {
        if (!this.runsTableBody) return;

        if (runs.length === 0) {
            this.runsTableBody.innerHTML = `
                <tr>
                    <td colspan="6" class="px-4 py-10 text-center text-slate-500">
                        <div class="flex flex-col items-center space-y-3">
                            <span class="text-3xl opacity-40">📄</span>
                            <span class="text-sm font-medium">No documents processed yet.</span>
                            <span class="text-xs text-slate-600">Upload a PDF or paste text above to start humanizing.</span>
                        </div>
                    </td>
                </tr>`;
            return;
        }

        const rows = runs.map(run => {
            const statusMap = {
                'completed': { label: 'Completed', cls: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
                'running':   { label: 'Processing', cls: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
                'failed':    { label: 'Failed', cls: 'bg-red-500/10 text-red-400 border-red-500/20' },
            };
            const statusInfo = statusMap[run.status] || { label: run.status || 'Unknown', cls: 'bg-slate-500/10 text-slate-400 border-slate-500/20' };

            // Format date/time
            let timeStr = run.start_time || '';
            try {
                const d = new Date(timeStr);
                timeStr = d.toLocaleString();
            } catch(e) {}

            // Type check: is it a PDF or Pasted Text run?
            const isPdf = run.filename && run.filename.toLowerCase().endsWith('.pdf');
            const typeLabel = isPdf ? '📄 PDF' : '✏️ Text';

            // Download button - only active if completed
            const downloadCell = run.status === 'completed'
                ? `<a href="${this.backendBaseUrl}/api/download/${run.run_id}" 
                       id="dl-btn-${run.run_id}"
                       class="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-gradient-to-r from-emerald-600/80 to-cyan-600/80 hover:from-emerald-500 hover:to-cyan-500 text-white text-xs font-bold rounded-lg shadow-md shadow-emerald-900/20 transition-all hover:scale-105 active:scale-95 cursor-pointer"
                       download>
                        <span>📥</span><span>Download</span>
                   </a>`
                : (run.status === 'running'
                    ? `<span class="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-slate-800/50 text-slate-500 text-xs font-semibold rounded-lg">
                           <span class="animate-pulse">⏳</span><span>In Progress</span>
                       </span>`
                    : `<span class="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-slate-800/50 text-slate-500 text-xs font-semibold rounded-lg">
                           <span>—</span><span>Unavailable</span>
                       </span>`);

            // Inline delete button action
            const actionButtons = `
                <div class="flex items-center justify-end space-x-2">
                    ${downloadCell}
                    <button class="inline-flex items-center justify-center p-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 rounded-lg border border-red-500/25 transition-all cursor-pointer"
                            onclick="window.appController && window.appController.deleteRun('${run.run_id}')"
                            title="Delete Record">
                        <span>🗑️</span>
                    </button>
                </div>
            `;

            return `
                <tr class="border-b border-slate-800/40 hover:bg-slate-800/20 transition-colors">
                    <td class="px-4 py-3 font-medium text-slate-200 max-w-[200px] truncate" title="${run.filename || ''}">
                        ${run.filename || 'Unknown'}
                    </td>
                    <td class="px-4 py-3 text-slate-400 font-semibold">
                        ${typeLabel}
                    </td>
                    <td class="px-4 py-3 text-slate-400">
                        ${run.total_chunks ?? '—'}
                    </td>
                    <td class="px-4 py-3 text-slate-500">
                        ${timeStr}
                    </td>
                    <td class="px-4 py-3">
                        <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${statusInfo.cls}">
                            ${statusInfo.label}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-right">
                        ${actionButtons}
                    </td>
                </tr>`;
        }).join('');

        this.runsTableBody.innerHTML = rows;
    }

    /**
     * Delete a single run and remove associated files
     * @param {string} runId 
     */
    async deleteRun(runId) {
        if (!confirm("Are you sure you want to permanently delete this record and all associated files from storage?")) {
            return;
        }

        try {
            const response = await fetch(`${this.backendBaseUrl}/api/runs/${runId}`, {
                method: 'DELETE'
            });

            if (!response.ok) throw new Error("Deletion failed on server.");

            console.log('Record successfully deleted:', runId);
            this.fetchRuns();
        } catch (err) {
            console.error('Delete run error:', err);
            this.showWarning(`Could not delete record: ${err.message}`);
        }
    }

    /**
     * Clear all records and files from history
     */
    async deleteAllRuns() {
        if (!confirm("WARNING: Are you sure you want to delete ALL records and data from history? This action is permanent and cannot be undone.")) {
            return;
        }

        try {
            const response = await fetch(`${this.backendBaseUrl}/api/runs`, {
                method: 'DELETE'
            });

            if (!response.ok) throw new Error("History purge failed on server.");

            console.log('All run history successfully cleared.');
            this.fetchRuns();
        } catch (err) {
            console.error('Purge error:', err);
            this.showWarning(`Could not clear history: ${err.message}`);
        }
    }

    /**
     * Update progress bars inside side column panel
     * @param {Array} providers 
     */
    updateQuotaBars(providers) {
        providers.forEach(p => {
            const percentage = p.remaining_percentage;
            const bar = document.getElementById(`quota-bar-${p.provider}`);
            const val = document.getElementById(`quota-val-${p.provider}`);

            if (bar && val) {
                bar.style.width = `${percentage}%`;
                val.textContent = `${percentage}%`;
            }
        });
    }

    /**
     * Process status changes on WebSocket Client channel
     * @param {string} status 'connected' | 'connecting' | 'disconnected'
     */
    handleWSStatusChange(status) {
        console.log(`WS Connection Status: ${status}`);
        
        // Clear classes
        this.wsBulb.className = 'w-2.5 h-2.5 rounded-full';
        
        if (status === 'connected') {
            this.wsBulb.classList.add('bg-emerald-500', 'shadow-lg');
            this.wsBulb.style.boxShadow = '0 0 10px rgba(16, 185, 129, 0.6)';
            this.wsText.textContent = 'Connected';
            this.fetchTokenStats(); // Refresh stats on connection
        } else if (status === 'connecting') {
            this.wsBulb.classList.add('bg-amber-500', 'shadow-lg');
            this.wsBulb.style.boxShadow = '0 0 10px rgba(245, 158, 11, 0.6)';
            this.wsText.textContent = 'Connecting...';
        } else {
            this.wsBulb.classList.add('bg-slate-500');
            this.wsBulb.style.boxShadow = 'none';
            this.wsText.textContent = 'Disconnected';
        }
    }

    /**
     * Parse and respond to live status broadcast events
     * @param {Object} data WebSocket JSON payload
     */
    handleWSMessage(data) {
        console.log('WS Message Received:', data);

        if (data.category === 'progress') {
            const state = data.progress_state;
            this.lastProgressState = state;
            
            // Format state name for visualization title
            const capitalized = state.charAt(0).toUpperCase() + state.slice(1);
            this.statsText.textContent = capitalized;

            this.pipelineView.updateState(state);

            if (state === 'completed') {
                this.resetPipeline('completed');
                this.fetchTokenStats();
                // Refresh runs list to show newly completed document
                setTimeout(() => this.fetchRuns(), 1500);
            } else if (state === 'failed') {
                this.resetPipeline('failed');
                this.setTextInputLock(false);
                // Refresh runs list to show failed status
                setTimeout(() => this.fetchRuns(), 1500);
            }
        } else if (data.category === 'text_completed') {
            // Text humanizer finished: fetch full inline text result content
            const targetRunId = data.run_id || this.activeRunId;
            if (targetRunId) {
                this.fetchTextResult(targetRunId);
            }
            this.resetPipeline('completed');
            this.fetchTokenStats();
            setTimeout(() => this.fetchRuns(), 1500);
        } else if (data.category === 'error') {
            this.showWarning("Pipeline run encountered a failover limit. Fallen back to alternate provider.");
            this.pipelineView.updateState(this.lastProgressState, true);
        } else if (data.category === 'token_update') {
            // Live token values update if present
            this.fetchTokenStats();
        }
    }

    /**
     * Reset execution locks and return to idle screen layouts
     */
    resetPipeline(status) {
        this.isProcessing = false;
        this.setUploadLock(false);
        this.fileInput.value = ''; // Reset file input

        if (status === 'completed') {
            this.statsText.textContent = 'Success - Done';
            
            const isTextMode = this.tabTextBtn.classList.contains('tab-active');

            if (!isTextMode) {
                // Transition upload zone into a success and download card for PDF mode
                this.uploadIcon.textContent = '✅';
                this.uploadTitle.textContent = "Document Processed Successfully!";
                this.uploadDesc.innerHTML = `
                    Your layout-preserved, humanized PDF is ready. Click below to download:<br>
                    <button id="download-doc-btn" class="mt-4 px-6 py-2.5 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-600 hover:to-cyan-600 text-slate-950 font-bold rounded-lg shadow-lg shadow-emerald-500/25 transition-all transform hover:scale-105 active:scale-95 cursor-pointer">
                        📥 Download Processed PDF
                    </button>
                    <br>
                    <span id="reset-upload-link" class="text-xs text-cyan-400 hover:text-cyan-300 underline mt-4 inline-block cursor-pointer">
                        Upload another document
                    </span>
                `;
                
                // Bind click download trigger
                const downloadBtn = document.getElementById('download-doc-btn');
                if (downloadBtn) {
                    downloadBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        window.location.href = `${this.backendBaseUrl}/api/download/${this.activeRunId}`;
                    });
                }
                
                // Bind reset trigger
                const resetLink = document.getElementById('reset-upload-link');
                if (resetLink) {
                    resetLink.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.restoreUploadZone();
                    });
                }
            } else {
                // In Text mode, the result is handled by fetchTextResult which displays it inline
                // But we should make sure we clear any text input locks
                this.setTextInputLock(false);
            }
        } else if (status === 'failed') {
            this.statsText.textContent = 'Failed';
            this.pipelineView.updateState(this.lastProgressState, true);
        } else {
            this.statsText.textContent = 'Idle';
            this.pipelineView.updateState('idle');
        }
    }

    /**
     * Reset upload center visual cards back to initial upload prompt
     */
    restoreUploadZone() {
        this.uploadIcon.textContent = '📥';
        this.uploadTitle.textContent = 'Upload Research Paper';
        this.uploadDesc.textContent = 'Drag and drop your PDF here, or click to browse files.';
        this.pipelineView.updateState('idle');
        this.statsText.textContent = 'Idle';
    }

    /**
     * Toggle lock guards on drag-drop interface inputs
     * @param {boolean} locked 
     */
    setUploadLock(locked) {
        if (locked) {
            this.uploadZone.style.pointerEvents = 'none';
            this.uploadZone.style.opacity = '0.6';
            this.uploadIcon.textContent = '🔄';
            this.uploadIcon.classList.add('animate-spin');
            this.uploadTitle.textContent = 'Processing Document...';
            this.uploadDesc.textContent = 'Analyzing syntax complexity and rewriting active blocks via failover waterfall.';
            this.uploadLoadingText.classList.remove('hidden');
        } else {
            this.uploadZone.style.pointerEvents = 'auto';
            this.uploadZone.style.opacity = '1.0';
            this.uploadIcon.textContent = '📥';
            this.uploadIcon.classList.remove('animate-spin');
            this.uploadTitle.textContent = 'Upload Research Paper';
            this.uploadDesc.textContent = 'Drag and drop your PDF here, or click to browse files.';
            this.uploadLoadingText.classList.add('hidden');
        }
    }

    /**
     * Toggle locks on text paste panel controls
     * @param {boolean} locked 
     */
    setTextInputLock(locked) {
        if (this.textInput) this.textInput.disabled = locked;
        if (this.clearTextBtn) this.clearTextBtn.disabled = locked;
        if (this.humanizeTextBtn) {
            this.humanizeTextBtn.disabled = locked;
            if (locked) {
                this.humanizeTextBtn.innerHTML = '<span>🔄</span><span>Processing...</span>';
                this.humanizeTextBtn.classList.add('opacity-75', 'cursor-not-allowed');
            } else {
                this.humanizeTextBtn.innerHTML = '<span>✨</span><span>Humanize Text</span>';
                this.humanizeTextBtn.classList.remove('opacity-75', 'cursor-not-allowed');
            }
        }
    }

    /**
     * Utility alerts methods
     */
    showWarning(message) {
        this.warningText.textContent = message;
        this.warningBox.classList.remove('hidden');
    }

    hideWarning() {
        this.warningBox.classList.add('hidden');
    }

    generateUUID() {
        // Robust random ID generator suitable for standard browser environments
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
            return crypto.randomUUID();
        }
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }
}

// Instantiate and bind to global DOM trigger once loaded
document.addEventListener('DOMContentLoaded', () => {
    window.appController = new HumanizerAppController();
});
