"use strict";
"use client";

import React, { useState, useEffect } from "react";
import "./jira_modal.css";

interface JiraSyncModalProps {
  projectId: string;
  isOpen: boolean;
  onClose: () => void;
  onSyncComplete?: (result: any) => void;
  mode?: "stories" | "tests";
}

export default function JiraSyncModal({
  projectId,
  isOpen,
  onClose,
  onSyncComplete,
  mode = "stories",
}: JiraSyncModalProps) {
  const [activeTab, setActiveTab] = useState<"sync" | "csv">("sync");
  const [isEnvConfigured, setIsEnvConfigured] = useState(false);
  const [hasApiTokenInEnv, setHasApiTokenInEnv] = useState(false);
  const [showConfigFields, setShowConfigFields] = useState(false);

  const [jiraUrl, setJiraUrl] = useState("");
  const [jiraEmail, setJiraEmail] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [projectKey, setProjectKey] = useState("AUTO");
  const [createEpic, setCreateEpic] = useState(true);
  const [createSprints, setCreateSprints] = useState(true);

  const [loadingConfig, setLoadingConfig] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<any | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const isTestMode = mode === "tests";

  useEffect(() => {
    if (isOpen && projectId) {
      setLoadingConfig(true);
      setErrorMsg(null);
      setSyncResult(null);
      setTestResult(null);
      fetch(`http://localhost:8000/api/projects/${projectId}/artifacts/backlog/jira/config`)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (data) {
            setIsEnvConfigured(data.configured_in_env);
            setHasApiTokenInEnv(data.has_api_token);
            if (data.jira_url) setJiraUrl(data.jira_url);
            if (data.jira_email) setJiraEmail(data.jira_email);
            if (data.suggested_project_key) setProjectKey(data.suggested_project_key);
          }
        })
        .catch(() => {})
        .finally(() => setLoadingConfig(false));
    }
  }, [isOpen, projectId, mode]);

  if (!isOpen) return null;

  const canSubmit = isEnvConfigured || (jiraUrl && jiraEmail && (apiToken || hasApiTokenInEnv));

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    setErrorMsg(null);

    try {
      const res = await fetch(
        `http://localhost:8000/api/projects/${projectId}/artifacts/backlog/jira/test-connection`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            jira_url: jiraUrl || undefined,
            jira_email: jiraEmail || undefined,
            jira_api_token: apiToken || undefined,
            jira_project_key: projectKey || undefined,
          }),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        setTestResult({ success: false, message: data.detail || "Connection failed" });
      } else {
        setTestResult(data);
      }
    } catch (err: any) {
      setTestResult({ success: false, message: err.message || "Failed to connect to API" });
    } finally {
      setTesting(false);
    }
  };

  const handleSyncToJira = async () => {
    setSyncing(true);
    setErrorMsg(null);
    setSyncResult(null);

    const syncUrl = isTestMode
      ? `http://localhost:8000/api/projects/${projectId}/artifacts/test_cases/jira/sync`
      : `http://localhost:8000/api/projects/${projectId}/artifacts/backlog/jira/sync`;

    const payload = isTestMode
      ? {
          jira_url: jiraUrl || undefined,
          jira_email: jiraEmail || undefined,
          jira_api_token: apiToken || undefined,
          jira_project_key: projectKey || undefined,
          create_epic: createEpic,
        }
      : {
          jira_url: jiraUrl || undefined,
          jira_email: jiraEmail || undefined,
          jira_api_token: apiToken || undefined,
          jira_project_key: projectKey || undefined,
          create_epic: createEpic,
          create_sprints: createSprints,
        };

    try {
      const res = await fetch(syncUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        setErrorMsg(data.detail || "Jira synchronization failed");
      } else {
        setSyncResult(data);
        if (onSyncComplete) {
          onSyncComplete(data);
        }
      }
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to execute sync");
    } finally {
      setSyncing(false);
    }
  };

  const handleDownloadCsv = () => {
    const csvUrl = isTestMode
      ? `http://localhost:8000/api/projects/${projectId}/artifacts/test_cases/download/jira-csv`
      : `http://localhost:8000/api/projects/${projectId}/artifacts/backlog/download/jira-csv`;
    window.open(csvUrl, "_blank");
  };

  return (
    <div className="jiraModalOverlay" onClick={onClose}>
      <div className="jiraModalCard" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="jiraModalHeader">
          <div className="jiraHeaderTitle">
            <div className="jiraIconBox">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M11.53 2c0 2.4 1.97 4.35 4.35 4.35h1.78v1.7c0 2.4 1.94 4.34 4.34 4.35V2h-10.47zM6.77 6.8c0 2.4 1.95 4.34 4.35 4.35h1.78v1.7c0 2.4 1.95 4.35 4.35 4.35V6.8H6.77zM2 11.6c0 2.4 1.95 4.34 4.35 4.35h1.78v1.7c0 2.4 1.95 4.35 4.35 4.35V11.6H2z"/>
              </svg>
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: "1.125rem", color: "#0f172a", fontWeight: 700 }}>
                {isTestMode ? "Jira Quality & Test Management" : "Jira Cloud Integration"}
              </h3>
              <span style={{ fontSize: "0.75rem", color: "#64748b" }}>
                {isTestMode
                  ? "Sync QA Test Cases, Scenarios, Steps & Traceability to Jira Cloud (Free Tier & Xray/Zephyr Compatible)"
                  : "Sync Sprint Plan & User Stories to Jira Software (Free Tier Compatible)"}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              fontSize: "1.25rem",
              color: "#64748b",
              cursor: "pointer",
              padding: "0.25rem 0.5rem",
            }}
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="jiraModalBody">
          <div className="jiraTabs">
            <button
              type="button"
              className={`jiraTabBtn ${activeTab === "sync" ? "active" : ""}`}
              onClick={() => setActiveTab("sync")}
            >
              Direct REST API Sync
            </button>
            <button
              type="button"
              className={`jiraTabBtn ${activeTab === "csv" ? "active" : ""}`}
              onClick={() => setActiveTab("csv")}
            >
              {isTestMode ? "Jira / Xray Test CSV Export" : "Zero-Config Jira CSV Export"}
            </button>
          </div>

          {activeTab === "sync" && (
            <>
              {syncResult ? (
                <div className="jiraSuccessCard">
                  <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>🎉</div>
                  <h4 style={{ margin: "0 0 0.5rem 0", color: "#15803d", fontSize: "1.125rem" }}>
                    Synchronization Successful!
                  </h4>
                  <p style={{ margin: 0, fontSize: "0.875rem", color: "#334155" }}>
                    {syncResult.message}
                  </p>

                  <div className="jiraStatsGrid">
                    {isTestMode ? (
                      <>
                        <div className="jiraStatBox">
                          <div className="jiraStatVal">{syncResult.tests_created}</div>
                          <div className="jiraStatLbl">Test Cases</div>
                        </div>
                        <div className="jiraStatBox">
                          <div className="jiraStatVal">{syncResult.epic_key || "N/A"}</div>
                          <div className="jiraStatLbl">Delivery Epic</div>
                        </div>
                        <div className="jiraStatBox">
                          <div className="jiraStatVal">{syncResult.project_key}</div>
                          <div className="jiraStatLbl">Project Key</div>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="jiraStatBox">
                          <div className="jiraStatVal">{syncResult.stories_created}</div>
                          <div className="jiraStatLbl">User Stories</div>
                        </div>
                        <div className="jiraStatBox">
                          <div className="jiraStatVal">{syncResult.sprints_created}</div>
                          <div className="jiraStatLbl">Sprints</div>
                        </div>
                        <div className="jiraStatBox">
                          <div className="jiraStatVal">{syncResult.epic_key || "N/A"}</div>
                          <div className="jiraStatLbl">Epic Key</div>
                        </div>
                      </>
                    )}
                  </div>

                  <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center", marginTop: "1rem" }}>
                    {syncResult.board_url && (
                      <a
                        href={syncResult.board_url}
                        target="_blank"
                        rel="noreferrer"
                        className="jiraBtn primary"
                        style={{ textDecoration: "none" }}
                      >
                        Open Jira Board ↗
                      </a>
                    )}
                    {syncResult.epic_url && (
                      <a
                        href={syncResult.epic_url}
                        target="_blank"
                        rel="noreferrer"
                        className="jiraBtn secondary"
                        style={{ textDecoration: "none" }}
                      >
                        View Epic in Jira ↗
                      </a>
                    )}
                  </div>
                </div>
              ) : (
                <>
                  {isEnvConfigured ? (
                    <div
                      style={{
                        background: "#f0fdf4",
                        border: "1px solid #bbf7d0",
                        borderRadius: "8px",
                        padding: "0.875rem 1rem",
                        marginBottom: "1rem",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 600, color: "#15803d", fontSize: "0.875rem" }}>
                          ✓ Loaded from Server (.env)
                        </div>
                        <div style={{ color: "#334155", fontSize: "0.8125rem", marginTop: "2px" }}>
                          <strong>{jiraUrl || "https://infrabeat.atlassian.net"}</strong> &bull; {jiraEmail}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => setShowConfigFields(!showConfigFields)}
                        style={{
                          fontSize: "0.75rem",
                          background: "#ffffff",
                          border: "1px solid #86efac",
                          borderRadius: "6px",
                          padding: "4px 8px",
                          color: "#166534",
                          cursor: "pointer",
                          fontWeight: 500,
                        }}
                      >
                        {showConfigFields ? "Hide Custom Details" : "Edit / Override"}
                      </button>
                    </div>
                  ) : null}

                  {(!isEnvConfigured || showConfigFields) && (
                    <>
                      <div className="jiraFormGroup">
                        <label>Jira Site URL</label>
                        <input
                          type="url"
                          className="jiraInput"
                          placeholder="https://your-domain.atlassian.net"
                          value={jiraUrl}
                          onChange={(e) => setJiraUrl(e.target.value)}
                        />
                        <span className="jiraHelpText">Your Atlassian Cloud workspace URL</span>
                      </div>

                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                        <div className="jiraFormGroup">
                          <label>Atlassian Account Email</label>
                          <input
                            type="email"
                            className="jiraInput"
                            placeholder="user@example.com"
                            value={jiraEmail}
                            onChange={(e) => setJiraEmail(e.target.value)}
                          />
                        </div>
                        <div className="jiraFormGroup">
                          <label>Jira Project Key</label>
                          <input
                            type="text"
                            className="jiraInput"
                            placeholder="e.g. GP or AUTO (auto-create)"
                            value={projectKey}
                            onChange={(e) => setProjectKey(e.target.value.toUpperCase())}
                          />
                        </div>
                      </div>

                      <div className="jiraFormGroup">
                        <label>Atlassian API Token</label>
                        <input
                          type="password"
                          className="jiraInput"
                          placeholder={hasApiTokenInEnv ? "•••••••••••••••• (Loaded from .env)" : "Paste your Atlassian API Token"}
                          value={apiToken}
                          onChange={(e) => setApiToken(e.target.value)}
                        />
                        <span className="jiraHelpText">
                          Create a free token at{" "}
                          <a
                            href="https://id.atlassian.com/manage-profile/security/api-tokens"
                            target="_blank"
                            rel="noreferrer"
                            className="jiraHelpLink"
                          >
                            id.atlassian.com/manage-profile/security/api-tokens ↗
                          </a>
                        </span>
                      </div>
                    </>
                  )}

                  <div className="jiraOptionsRow">
                    <label className="jiraCheckboxLabel">
                      <input
                        type="checkbox"
                        checked={createEpic}
                        onChange={(e) => setCreateEpic(e.target.checked)}
                      />
                      <span>
                        {isTestMode
                          ? "Link Test Cases under Delivery Epic (Test Pack Parent)"
                          : "Create Project Epic (Parent for all user stories)"}
                      </span>
                    </label>
                    {!isTestMode && (
                      <label className="jiraCheckboxLabel">
                        <input
                          type="checkbox"
                          checked={createSprints}
                          onChange={(e) => setCreateSprints(e.target.checked)}
                        />
                        <span>Create &amp; schedule Sprints on Scrum Board with 2-week dates</span>
                      </label>
                    )}
                  </div>

                  {testResult && (
                    <div className={`jiraAlert ${testResult.success ? "success" : "error"}`}>
                      {testResult.success ? "✓ " : "⚠ "}
                      {testResult.message}
                    </div>
                  )}

                  {errorMsg && (
                    <div className="jiraAlert error">
                      ⚠ {errorMsg}
                    </div>
                  )}
                </>
              )}
            </>
          )}

          {activeTab === "csv" && (
            <div>
              <div className="jiraAlert info" style={{ marginBottom: "1rem" }}>
                ℹ <strong>Zero Credentials Required:</strong> Download a pre-formatted Jira / Zephyr / Xray CSV file that can be imported directly into any Jira Cloud instance via <em>Settings → System → External System Import (CSV)</em>.
              </div>
              <p style={{ fontSize: "0.875rem", color: "#475569", lineHeight: 1.5 }}>
                {isTestMode ? (
                  <>
                    The CSV contains all <strong>QA Test Cases</strong>, <strong>Preconditions</strong>, <strong>Execution Steps</strong>, <strong>Expected Results</strong>, <strong>Priorities</strong>, and <strong>BRD Traceability Citations</strong>.
                  </>
                ) : (
                  <>
                    The CSV contains all <strong>User Stories</strong>, <strong>Acceptance Criteria</strong>, <strong>Story Points (5/3 pts)</strong>, <strong>Sprint Groupings</strong>, <strong>Priorities</strong>, and <strong>BRD Traceability Labels</strong>.
                  </>
                )}
              </p>
              <div style={{ marginTop: "1.5rem", textAlign: "center" }}>
                <button
                  type="button"
                  onClick={handleDownloadCsv}
                  className="jiraBtn primary"
                  style={{ padding: "0.75rem 1.5rem", fontSize: "0.9375rem" }}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                  </svg>
                  {isTestMode ? "Download Jira Test CSV (.csv)" : "Download Jira-Ready CSV (.csv)"}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="jiraModalFooter">
          <button type="button" className="jiraBtn secondary" onClick={onClose}>
            {syncResult ? "Close" : "Cancel"}
          </button>
          {activeTab === "sync" && !syncResult && (
            <>
              <button
                type="button"
                className="jiraBtn test"
                onClick={handleTestConnection}
                disabled={testing || !canSubmit}
              >
                {testing ? "Testing..." : "Test Connection"}
              </button>
              <button
                type="button"
                className="jiraBtn primary"
                onClick={handleSyncToJira}
                disabled={syncing || !canSubmit}
              >
                {syncing
                  ? isTestMode
                    ? "Syncing Test Cases..."
                    : "Syncing to Jira..."
                  : isTestMode
                  ? "Sync Test Cases to Jira"
                  : "Sync Sprint Plan to Jira"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
