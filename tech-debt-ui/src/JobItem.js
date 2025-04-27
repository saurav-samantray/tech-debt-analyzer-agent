// src/JobItem.js
import React, { useState } from 'react';

// --- Helper Functions (Copied from App.js or imported if moved) ---
function getCategoryClassName(category = 'unknown') {
  return `category-${category
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9-]/g, '')}`;
}

function getSeverityClassName(severity = 'unknown') {
  const lowerSeverity = severity.toLowerCase();
  switch (lowerSeverity) {
    case 'low':
      return 'severity-low';
    case 'medium':
      return 'severity-medium';
    case 'high':
      return 'severity-high';
    default:
      return 'severity-unknown';
  }
}
// --- End Helper Functions ---

function JobItem({ job }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const toggleExpand = () => {
    setIsExpanded(!isExpanded);
  };

  if (!job) return null; // Should not happen, but safety check

  const submittedDate = job.submitted_at ? new Date(job.submitted_at * 1000).toLocaleString() : 'N/A';
  const duration = job.duration_seconds ? `${job.duration_seconds.toFixed(2)}s` : '-';
  const hasFindings = job.status === 'COMPLETED' && job.findings && job.findings.length > 0;
  const canExpand = job.status === 'COMPLETED' || job.status === 'FAILED'; // Only allow expanding finished jobs

  return (
    <li className={`job-list-item ${canExpand ? 'expandable' : ''}`}>
      {/* --- Clickable Header --- */}
      <div className="job-item-header" onClick={canExpand ? toggleExpand : undefined}>
        <div className="job-header-main">
            <span className="job-repo">{job.repo_url || 'N/A'}</span>
            <span className={`job-status ${job.status}`}>{job.status}</span>
        </div>
        <div className="job-header-meta">
            <span className="job-id">{job.job_id}</span>
            <span>| Submitted: {submittedDate}</span>
            {canExpand && (
                <span className="expand-indicator">{isExpanded ? '[-] Collapse' : '[+] Expand'}</span>
            )}
        </div>
      </div>

      {/* --- Collapsible Details --- */}
      {isExpanded && canExpand && (
        <div className="job-item-details">
          <p><strong>LLM Type:</strong> {job.llm_type || 'N/A'}</p>
          {job.status === 'COMPLETED' && <p><strong>Duration:</strong> {duration}</p>}
          {job.status === 'COMPLETED' && <p><strong>Files Scanned:</strong> {job.files_scanned ?? 0} / {job.total_files ?? 0}</p>}
          {job.status === 'FAILED' && <p><strong>Error:</strong> <span style={{ color: 'var(--danger-color)' }}>{job.error || 'Unknown error'}</span></p>}

          {/* --- Tabular Findings --- */}
          {hasFindings && (
            <div className="findings-list">
              <h4>Findings ({job.findings.length}):</h4>
              <div className="table-container"> {/* Added container for potential horizontal scroll */}
                <table className="findings-table">
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Severity</th>
                      <th>File</th>
                      <th>Line</th>
                      <th>Description</th>
                      <th>Norm Violated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {job.findings.map((finding, index) => (
                      <tr key={index}>
                        {/* Category Cell with Color Dot */}
                        <td>
                          <span className={`category-dot ${getCategoryClassName(finding.category)}`}></span>
                          {finding.category || 'Unknown'}
                        </td>
                        {/* Severity Cell with Badge */}
                        <td>
                          <span className={`severity-badge ${getSeverityClassName(finding.severity)}`}>
                            {finding.severity || 'Unknown'}
                          </span>
                        </td>
                        {/* File Cell */}
                        <td className="cell-file"><code>{finding.file}</code></td>
                        {/* Line Cell */}
                        <td className="cell-line">{finding.line_number}</td>
                        {/* Description Cell */}
                        <td className="cell-description">{finding.description}</td>
                        {/* Norm Cell */}
                        <td className="cell-norm">{finding.norm_violated || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {job.status === 'COMPLETED' && (!job.findings || job.findings.length === 0) && (
             <p><em>No findings reported for this job.</em></p>
          )}
        </div>
      )}
    </li>
  );
}

export default JobItem;
