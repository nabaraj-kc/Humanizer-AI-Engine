/**
 * frontend/js/pipeline_view.js
 * ============================
 * Pipeline status Node Map SVG visualizer.
 * Generates an interactive SVG timeline showing pipeline states, node glows,
 * and path transitions.
 */

class PipelineNodeView {
    /**
     * @param {string} containerId Parent DOM container ID.
     */
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.error(`PipelineNodeView container '#${containerId}' not found.`);
            return;
        }

        this.svg = null;
        this.nodes = [
            { id: 'ingest', label: 'File Ingest', progressStateMatch: ['parsing'] },
            { id: 'analysis', label: 'Adversarial Analysis', progressStateMatch: ['analyzing'] },
            { id: 'rewriting', label: 'Waterfall Rewrite', progressStateMatch: ['rewriting'] },
            { id: 'reconstruct', label: 'Layout Reconstruct', progressStateMatch: ['reconstruction'] },
            { id: 'assembly', label: 'Redact & Merge', progressStateMatch: ['assembly'] },
            { id: 'export', label: 'PDF Export', progressStateMatch: ['completed'] }
        ];

        // Current status for each node: 'idle', 'processing', 'success', 'error'
        this.nodeStates = {};
        this.initStates();

        // Initialize SVG canvas
        this.setupCanvas();

        // Listen for container resize
        window.addEventListener('resize', () => this.draw());
    }

    /**
     * Set all nodes back to idle
     */
    initStates() {
        this.nodes.forEach(node => {
            this.nodeStates[node.id] = 'idle';
        });
    }

    /**
     * Instantiate SVG container and clear fallbacks
     */
    setupCanvas() {
        this.container.innerHTML = ''; // Clear fallback text
        this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        this.svg.setAttribute('width', '100%');
        this.svg.setAttribute('height', '100%');
        this.svg.setAttribute('class', 'w-full h-full min-h-[300px]');
        this.container.appendChild(this.svg);

        // Add filter effects for neon glow
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        defs.innerHTML = `
            <filter id="glow-purple" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="6" result="blur" />
                <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                </feMerge>
            </filter>
            <filter id="glow-green" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="6" result="blur" />
                <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                </feMerge>
            </filter>
            <filter id="glow-red" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="6" result="blur" />
                <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                </feMerge>
            </filter>
        `;
        this.svg.appendChild(defs);
    }

    /**
     * Update node states based on the progress status update
     * @param {string} progressState Current active state ('idle', 'parsing', 'rewriting', 'completed', etc.)
     * @param {boolean} isFailed Whether the pipeline run encountered an error
     */
    updateState(progressState, isFailed = false) {
        if (!progressState || progressState === 'idle') {
            this.initStates();
            this.draw();
            return;
        }

        // Map progress_state to our internal nodes indices
        let activeIndex = -1;
        if (progressState === 'parsing') activeIndex = 0;
        else if (progressState === 'analyzing') activeIndex = 1;
        else if (progressState === 'rewriting') activeIndex = 2;
        else if (progressState === 'reconstruction') activeIndex = 3;
        else if (progressState === 'assembly') activeIndex = 4;
        else if (progressState === 'completed') activeIndex = 5;

        // If activeIndex is -1 but we received a success/failure, handle edges
        if (progressState === 'completed') {
            activeIndex = 5;
        }

        this.nodes.forEach((node, idx) => {
            if (isFailed && idx === activeIndex) {
                this.nodeStates[node.id] = 'error';
            } else if (idx < activeIndex) {
                this.nodeStates[node.id] = 'success';
            } else if (idx === activeIndex) {
                this.nodeStates[node.id] = isFailed ? 'error' : 'processing';
            } else {
                this.nodeStates[node.id] = 'idle';
            }
        });

        // Special case: if completed, everything is success
        if (progressState === 'completed' && !isFailed) {
            this.nodes.forEach(node => {
                this.nodeStates[node.id] = 'success';
            });
        }

        this.draw();
    }

    /**
     * Redraw the node map SVG elements
     */
    draw() {
        if (!this.svg) return;

        // Remove existing graphical elements except defs
        const elements = this.svg.querySelectorAll('circle, path, text, g');
        elements.forEach(el => el.remove());

        const width = this.container.clientWidth || 800;
        const height = this.container.clientHeight || 300;

        // Setup layouts parameters
        const paddingX = 60;
        const totalNodes = this.nodes.length;
        const nodeSpacing = (width - paddingX * 2) / (totalNodes - 1);
        const centerY = height / 2 - 10;

        const coords = this.nodes.map((node, idx) => {
            return {
                id: node.id,
                x: paddingX + idx * nodeSpacing,
                y: centerY
            };
        });

        // 1. Draw connecting paths first (so they are layered under circles)
        for (let i = 0; i < coords.length - 1; i++) {
            const start = coords[i];
            const end = coords[i + 1];
            const startState = this.nodeStates[start.id];
            const endState = this.nodeStates[end.id];

            let pathClass = 'path-idle';
            if (startState === 'success' && endState === 'success') {
                pathClass = 'path-success';
            } else if (startState === 'success' && endState === 'processing') {
                pathClass = 'path-processing';
            } else if (startState === 'success' && endState === 'error') {
                pathClass = 'path-error';
            } else if (startState === 'processing') {
                pathClass = 'path-processing';
            }

            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', `M ${start.x} ${start.y} L ${end.x} ${end.y}`);
            path.setAttribute('class', `node-path ${pathClass}`);
            this.svg.appendChild(path);
        }

        // 2. Draw nodes circles and labels
        coords.forEach((coord, idx) => {
            const state = this.nodeStates[coord.id];
            const nodeInfo = this.nodes[idx];

            let nodeClass = 'node-idle';
            let filterEffect = '';

            if (state === 'processing') {
                nodeClass = 'node-processing';
                filterEffect = 'url(#glow-purple)';
            } else if (state === 'success') {
                nodeClass = 'node-success';
                filterEffect = 'url(#glow-green)';
            } else if (state === 'error') {
                nodeClass = 'node-error';
                filterEffect = 'url(#glow-red)';
            }

            // Create a group for interactive scaling hover effects
            const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            g.setAttribute('class', 'cursor-pointer group');

            // SVG Circle
            const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            circle.setAttribute('cx', coord.x);
            circle.setAttribute('cy', coord.y);
            circle.setAttribute('r', state === 'processing' ? '14' : '10');
            circle.setAttribute('class', `node-circle ${nodeClass}`);
            if (filterEffect) {
                circle.setAttribute('filter', filterEffect);
            }
            g.appendChild(circle);

            // Text Label
            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', coord.x);
            text.setAttribute('y', coord.y + 35);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('class', 'fill-slate-400 text-[10px] sm:text-xs font-semibold tracking-wide');
            if (state === 'processing') {
                text.setAttribute('class', 'fill-violet-400 text-[10px] sm:text-xs font-bold tracking-wide');
            } else if (state === 'success') {
                text.setAttribute('class', 'fill-emerald-400 text-[10px] sm:text-xs font-semibold tracking-wide');
            } else if (state === 'error') {
                text.setAttribute('class', 'fill-red-400 text-[10px] sm:text-xs font-bold tracking-wide');
            }
            text.textContent = nodeInfo.label;
            g.appendChild(text);

            // Optional Step Number inside Circle
            const stepNum = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            stepNum.setAttribute('x', coord.x);
            stepNum.setAttribute('y', coord.y + 4);
            stepNum.setAttribute('text-anchor', 'middle');
            stepNum.setAttribute('class', 'fill-slate-200 text-[9px] font-bold pointer-events-none');
            stepNum.textContent = idx + 1;
            g.appendChild(stepNum);

            this.svg.appendChild(g);
        });
    }
}

// Expose to global window scope
if (typeof window !== 'undefined') {
    window.PipelineNodeView = PipelineNodeView;
}
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { PipelineNodeView };
}
