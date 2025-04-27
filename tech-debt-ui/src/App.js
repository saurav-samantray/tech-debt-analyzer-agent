// src/App.js
import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import './App.css';
import JobItem from './JobItem'; // Import the new component

// --- Configuration ---
const API_BASE_URL = 'http://localhost:5001';
const POLLING_INTERVAL = 5000;

// Remove helper functions if they are now only in JobItem.js
// function getCategoryClassName(...) { ... }
// function getSeverityClassName(...) { ... }

function App() {
  // --- State ---
  const [repoUrl, setRepoUrl] = useState('');
  const [llmType, setLlmType] = useState('ollama');
  const [jobs, setJobs] = useState({});
  const [isLoadingScan, setIsLoadingScan] = useState(false);
  const [isLoadingRag, setIsLoadingRag] = useState(false);
  const [error, setError] = useState(null);
  const [ragStatus, setRagStatus] = useState('');

  // --- API Functions ---
  const api = axios.create({
    baseURL: API_BASE_URL,
    headers: { 'Content-Type': 'application/json' },
  });

  // --- Effects ---
  useEffect(() => {
    const intervalId = setInterval(() => {
      const activeJobIds = Object.entries(jobs)
        .filter(([_, job]) => ['PENDING', 'RUNNING', 'CLONING', 'INITIALIZING_RAG', 'FINDING_FILES', 'ANALYZING'].includes(job.status))
        .map(([jobId, _]) => jobId);

      if (activeJobIds.length > 0) {
        activeJobIds.forEach(jobId => fetchJobStatus(jobId));
      }
    }, POLLING_INTERVAL);

    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs]);


  // --- Handlers ---
  const handleScanSubmit = async (event) => {
    event.preventDefault();
    setError(null);
    setIsLoadingScan(true);

    try {
      const response = await api.post('/scan', { repo_url: repoUrl, llm_type: llmType });
      const newJob = response.data;
      setJobs(prevJobs => ({
        ...prevJobs,
        [newJob.job_id]: newJob
      }));
      setRepoUrl('');
    } catch (err) {
      console.error("Scan initiation failed:", err);
      const errorDetails = err.response?.data?.details;
      let errorMsg = err.response?.data?.error || err.message || 'Failed to start scan.';
      if (errorDetails) {
          errorMsg += ` Details: ${JSON.stringify(errorDetails)}`;
      }
      setError(errorMsg);
    } finally {
      setIsLoadingScan(false);
    }
  };

  const fetchJobStatus = useCallback(async (jobId) => {
    try {
      const response = await api.get(`/status/${jobId}`);
      const updatedJob = response.data;
      setJobs(prevJobs => {
        // Prevent unnecessary re-renders if data hasn't changed
        if (prevJobs[jobId] && JSON.stringify(prevJobs[jobId]) !== JSON.stringify(updatedJob)) {
          return { ...prevJobs, [jobId]: updatedJob };
        }
        // If job doesn't exist yet or data is same, return previous state
        return prevJobs[jobId] ? prevJobs : { ...prevJobs, [jobId]: updatedJob };
      });
    } catch (err) {
      console.error(`Failed to fetch status for job ${jobId}:`, err);
      // Optionally update job status to indicate fetch error
    }
  }, [api]); // api dependency is stable

  const handleRagRebuild = async () => {
    setError(null);
    setIsLoadingRag(true);
    setRagStatus('Rebuilding index...');
    try {
      const response = await api.post('/rag/rebuild');
      setRagStatus(response.data?.message || 'RAG index rebuild successful!');
    } catch (err) {
      console.error("RAG rebuild failed:", err);
      const errorMsg = err.response?.data?.error || err.message || 'Failed to rebuild RAG index.';
      setError(`RAG Rebuild Failed: ${errorMsg}`);
      setRagStatus('');
    } finally {
      setIsLoadingRag(false);
      setTimeout(() => {
        if (!error) setRagStatus('');
      }, 5000);
    }
  };

  // --- Rendering ---
  const sortedJobIds = Object.keys(jobs).sort((a, b) => (jobs[b].submitted_at || 0) - (jobs[a].submitted_at || 0));

  return (
    <div className="App">
      <h1><span role="img" aria-label="robot">🤖</span> Agentic Tech Debt Analyzer</h1>

      {error && <div className="error-message">{error}</div>}

      {/* --- Scan Section (Keep horizontal layout) --- */}
      <div className="section scan-form">
        <h2><span role="img" aria-label="magnifying glass">🔍</span> Start New Scan</h2>
        <form onSubmit={handleScanSubmit} className="scan-form-horizontal">
          <div className="form-group form-group-repo">
            <label htmlFor="repoUrl">Repository URL:</label>
            <input
              type="text"
              id="repoUrl"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="e.g., https://github.com/pallets/flask.git"
              required
            />
          </div>
          <div className="form-group form-group-llm">
            <label htmlFor="llmType">LLM Type:</label>
            <select
              id="llmType"
              value={llmType}
              onChange={(e) => setLlmType(e.target.value)}
            >
              <option value="ollama">Ollama (Local)</option>
              <option value="openai">OpenAI (API)</option>
            </select>
          </div>
          <button type="submit" disabled={isLoadingScan} className="scan-button">
            {isLoadingScan ? 'Starting...' : 'Start Scan'}
          </button>
        </form>
      </div>

      {/* --- Job List Section --- */}
      <div className="section job-list">
        <h2><span role="img" aria-label="clipboard">📋</span> Scan Jobs</h2>
        {sortedJobIds.length === 0 ? (
          <p>No scan jobs initiated yet.</p>
        ) : (
          <ul>
            {/* Use the JobItem component */}
            {sortedJobIds.map(jobId => (
              <JobItem key={jobId} job={jobs[jobId]} />
            ))}
          </ul>
        )}
      </div>

      {/* --- RAG Control Section --- */}
      <div className="section rag-control">
        <h2><span role="img" aria-label="books">📚</span> RAG Index Control</h2>
        <button onClick={handleRagRebuild} disabled={isLoadingRag}>
          {isLoadingRag ? 'Rebuilding...' : 'Rebuild RAG Index'}
        </button>
        {ragStatus && <p className="status-message">{ragStatus}</p>}
        <p><small>Rebuild the index if you have updated the documents in the backend's 'norms' directory.</small></p>
      </div>
    </div>
  );
}

export default App;
