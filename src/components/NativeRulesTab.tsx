import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  FilePlus2,
  FileText,
  FolderOpen,
  FolderPlus,
  NotebookPen,
  RefreshCw,
} from "lucide-react";
import { MarkdownDocView } from "./MarkdownDocView";
import { SearchInput, SegmentedControl, StatusPill } from "./MotionPrimitives";
import { formatBytes, formatErrorMessage, formatMtime } from "../lib/format";
import { ipc } from "../lib/ipc";
import type {
  DiscoveredProject,
  ProjectRulesOverview,
  RuleFileContent,
  RuleFileInfo,
} from "../types/ipc";

type ProjectFilterMode = "with-rules" | "all";
type PreviewMode = "rendered" | "raw";

interface NativeRulesTabProps {
  overview: ProjectRulesOverview | null;
  loading: boolean;
  onRefresh: () => void;
  onPickProject: () => void;
  onOpenUrl: (url: string) => void;
  onToast: (message: string, tone?: "info" | "ok" | "warn" | "error") => void;
}

export function NativeRulesTab({
  overview,
  loading,
  onRefresh,
  onPickProject,
  onOpenUrl,
  onToast,
}: NativeRulesTabProps) {
  const [query, setQuery] = useState("");
  const [projectFilter, setProjectFilter] = useState<ProjectFilterMode>("with-rules");
  const [previewMode, setPreviewMode] = useState<PreviewMode>("rendered");
  const [selectedRuleId, setSelectedRuleId] = useState<string>("");
  const [contentData, setContentData] = useState<RuleFileContent | null>(null);
  const [contentLoading, setContentLoading] = useState(false);

  const projects = overview?.projects ?? [];

  const allRules = useMemo(() => {
    const list: RuleFileInfo[] = [];
    for (const p of projects) {
      for (const r of p.ruleFiles) {
        list.push(r);
      }
    }
    return list;
  }, [projects]);

  const selectedRule = useMemo(
    () => allRules.find((r) => r.id === selectedRuleId) ?? allRules[0] ?? null,
    [allRules, selectedRuleId],
  );

  const loadRuleContent = useCallback(
    async (fullPath: string, silent = false) => {
      if (!fullPath) {
        setContentData(null);
        return;
      }
      if (!silent) setContentLoading(true);
      try {
        const res = await ipc.readRuleFile(fullPath);
        setContentData(res);
      } catch (err) {
        if (!silent) {
          onToast(`读取规则文件失败：${formatErrorMessage(err)}`, "error");
        }
      } finally {
        if (!silent) setContentLoading(false);
      }
    },
    [onToast],
  );

  useEffect(() => {
    if (selectedRule) {
      loadRuleContent(selectedRule.fullPath);
    } else {
      setContentData(null);
    }
  }, [selectedRule, loadRuleContent]);

  // Auto-reload current rule file when returning from Windows Notepad
  useEffect(() => {
    const onFocus = () => {
      if (selectedRule) {
        loadRuleContent(selectedRule.fullPath, true);
      }
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [selectedRule, loadRuleContent]);

  const filteredProjects = useMemo(() => {
    const q = query.trim().toLowerCase();
    return projects
      .filter((p) => {
        if (!p.exists && p.ruleFiles.length === 0) return false;
        if (projectFilter === "with-rules" && p.ruleFiles.length === 0) return false;
        if (q) {
          const projMatch = `${p.name} ${p.rootPath}`.toLowerCase().includes(q);
          const fileMatch = p.ruleFiles.some((r) =>
            `${r.fileName} ${r.relPath}`.toLowerCase().includes(q),
          );
          if (!projMatch && !fileMatch) return false;
        }
        return true;
      });
  }, [projects, projectFilter, query]);

  const withRulesCount = useMemo(
    () => projects.filter((p) => p.ruleFiles.length > 0).length,
    [projects],
  );
  const existingProjectsCount = useMemo(
    () => projects.filter((p) => p.exists).length,
    [projects],
  );

  const handleOpenInNotepad = async (filePath: string) => {
    try {
      await ipc.openInNotepad(filePath);
    } catch (err) {
      onToast(`启动 Windows 记事本失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleCreateAndEdit = async (proj: DiscoveredProject, fileName: "AGENTS.md" | "GEMINI.md") => {
    try {
      const created = await ipc.createRuleFileAndOpenNotepad(proj.rootPath, fileName);
      setSelectedRuleId(created.id);
      onRefresh();
    } catch (err) {
      onToast(`创建 ${fileName} 失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const handleOpenExplorer = async (path: string) => {
    try {
      await ipc.openPathInExplorer(path);
    } catch (err) {
      onToast(`打开目录失败：${formatErrorMessage(err)}`, "error");
    }
  };

  const filterOptions: Array<{ key: ProjectFilterMode; label: string; count: number }> = [
    { key: "with-rules", label: "含规则文件", count: withRulesCount },
    { key: "all", label: "全部项目", count: existingProjectsCount },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* Toolbar */}
      <div className="agy-card flex flex-wrap items-center justify-between gap-2.5 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="搜索项目名称或 AGENTS.md / GEMINI.md..."
            className="w-[245px]"
          />
          <SegmentedControl
            options={filterOptions}
            value={projectFilter}
            onChange={setProjectFilter}
            layoutId="native-rules-filter"
            ariaLabel="筛选项目"
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onPickProject}
            className="agy-btn px-2.5 py-1.5 text-[12px]"
            title="添加本地项目文件夹以扫描 AGENTS.md / GEMINI.md"
          >
            <FolderPlus className="h-3.5 w-3.5" />
            <span>添加项目</span>
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={() => {
              onRefresh();
              if (selectedRule) loadRuleContent(selectedRule.fullPath);
            }}
            className="agy-btn px-2.5 py-1.5 text-[12px]"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>刷新</span>
          </button>
        </div>
      </div>

      {/* Master-Detail Split Workspace */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3.5 lg:grid-cols-[340px_1fr]">
        {/* Left: Project & Rule Files List */}
        <section className="agy-card flex min-h-0 flex-col overflow-hidden">
          <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-2.5">
            {filteredProjects.length === 0 ? (
              <div className="flex h-full min-h-[180px] items-center justify-center px-4 text-center text-[12.5px] text-[var(--text-muted)]">
                {allRules.length > 0 ? "未找到匹配的项目或规则文件" : "暂未发现 AGENTS.md 或 GEMINI.md"}
              </div>
            ) : (
              filteredProjects.map((proj) => {
                const hasRootAgents = proj.ruleFiles.some(
                  (r) => r.relPath.toLowerCase() === "agents.md",
                );
                const hasRootGemini = proj.ruleFiles.some(
                  (r) => r.relPath.toLowerCase() === "gemini.md",
                );

                return (
                  <div
                    key={proj.id}
                    className="rounded-xl border border-[var(--border-hairline)] bg-[var(--bg-surface-soft)] p-2.5"
                  >
                    <div className="flex items-start justify-between gap-2 px-1">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-[12.5px] font-semibold text-[var(--text-primary)]">
                            {proj.name}
                          </span>
                          {proj.source === "global" && (
                            <StatusPill tone="ok">全局</StatusPill>
                          )}
                        </div>
                        <p className="mt-0.5 truncate font-mono-code text-[10.5px] text-[var(--text-faint)]">
                          {proj.rootPath}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleOpenExplorer(proj.rootPath)}
                        title="在资源管理器中打开项目目录"
                        className="shrink-0 cursor-pointer rounded-md p-1 text-[var(--text-faint)] transition-colors hover:bg-[var(--bg-subtle)] hover:text-[var(--text-primary)]"
                      >
                        <FolderOpen className="h-3.5 w-3.5" />
                      </button>
                    </div>

                    {proj.ruleFiles.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {proj.ruleFiles.map((rf) => {
                          const active = selectedRule?.id === rf.id;
                          return (
                            <div
                              key={rf.id}
                              onClick={() => setSelectedRuleId(rf.id)}
                              className={`flex cursor-pointer items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 transition-colors ${
                                active
                                  ? "bg-[var(--bg-surface)] shadow-[var(--shadow-card)] ring-1 ring-[var(--border-strong)]"
                                  : "hover:bg-[var(--bg-surface)]"
                              }`}
                            >
                              <div className="flex min-w-0 items-center gap-2">
                                <FileText
                                  className="h-3.5 w-3.5 shrink-0"
                                  style={{
                                    color:
                                      rf.kind === "gemini" ? "var(--info)" : "var(--accent)",
                                  }}
                                />
                                <span className="truncate font-mono-code text-[12px] font-medium text-[var(--text-primary)]">
                                  {rf.relPath}
                                </span>
                              </div>
                              <div className="flex shrink-0 items-center gap-1.5">
                                {rf.overLimit && (
                                  <span
                                    title="超过 Antigravity 单文件 24 KB 规则上下文限制，超出部分会被截断"
                                    className="rounded bg-[var(--warn-bg)] px-1 py-[1px] text-[10px] font-semibold text-[var(--warn)]"
                                  >
                                    &gt;24KB
                                  </span>
                                )}
                                <span className="font-mono-code text-[10.5px] tabular-nums text-[var(--text-faint)]">
                                  {formatBytes(rf.sizeBytes)}
                                </span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {(!hasRootAgents || !hasRootGemini) && (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5 px-1">
                        {!hasRootAgents && (
                          <button
                            type="button"
                            onClick={() => handleCreateAndEdit(proj, "AGENTS.md")}
                            className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-dashed border-[var(--border-strong)] px-2 py-0.5 text-[11px] text-[var(--text-muted)] transition-colors hover:border-[var(--accent)] hover:text-[var(--text-primary)]"
                          >
                            <FilePlus2 className="h-3 w-3" />
                            <span>新建 AGENTS.md</span>
                          </button>
                        )}
                        {!hasRootGemini && (
                          <button
                            type="button"
                            onClick={() => handleCreateAndEdit(proj, "GEMINI.md")}
                            className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-dashed border-[var(--border-strong)] px-2 py-0.5 text-[11px] text-[var(--text-muted)] transition-colors hover:border-[var(--info)] hover:text-[var(--text-primary)]"
                          >
                            <FilePlus2 className="h-3 w-3" />
                            <span>新建 GEMINI.md</span>
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* Right: Read-only Preview + Direct Windows Notepad Launch */}
        <section className="agy-card flex min-h-0 flex-col overflow-hidden">
          {!selectedRule ? (
            <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-2 px-6 text-center text-[13px] text-[var(--text-muted)]">
              <FileText className="h-8 w-8 text-[var(--text-faint)]" />
              <p>从左侧选择任意 `AGENTS.md` 或 `GEMINI.md` 进行预览，或点击「用记事本编辑」</p>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-hairline)] px-5 py-3.5">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="truncate font-mono-code text-[14.5px] font-bold text-[var(--text-primary)]">
                      {selectedRule.relPath}
                    </h3>
                    <StatusPill tone={selectedRule.scope === "global" ? "ok" : "info"}>
                      {selectedRule.projectName}
                    </StatusPill>
                  </div>
                  <p className="mt-0.5 truncate font-mono-code text-[11px] text-[var(--text-faint)] select-text">
                    {selectedRule.fullPath} · {formatBytes(contentData?.sizeBytes ?? selectedRule.sizeBytes)} · 更新于{" "}
                    {formatMtime(contentData?.modifiedAt ?? selectedRule.modifiedAt)}
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <SegmentedControl
                    options={[
                      { key: "rendered", label: "Markdown" },
                      { key: "raw", label: "原文" },
                    ]}
                    value={previewMode}
                    onChange={setPreviewMode}
                    layoutId="rule-preview-mode"
                    ariaLabel="预览模式"
                  />

                  <button
                    type="button"
                    onClick={() => handleOpenExplorer(selectedRule.fullPath)}
                    className="agy-btn px-2.5 py-1.5 text-[12px]"
                    title="在资源管理器中定位文件"
                  >
                    <FolderOpen className="h-3.5 w-3.5" />
                    <span>定位</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleOpenInNotepad(selectedRule.fullPath)}
                    className="agy-btn-primary px-3.5 py-1.5 text-[12.5px]"
                    title="直接使用 Windows 记事本打开编辑（保存后切回本窗口自动刷新）"
                  >
                    <NotebookPen className="h-3.5 w-3.5" />
                    <span>用记事本编辑</span>
                  </button>
                </div>
              </div>

              {(contentData?.overLimit ?? selectedRule.overLimit) && (
                <div className="flex items-center gap-2 border-b border-[var(--border-hairline)] bg-[var(--warn-bg)] px-5 py-2 text-[12px] text-[var(--warn)]">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>
                    文件体积超过 Antigravity 单规则 24 KB（24,000 字节）上限，超出部分在对话注入时可能被按行截断。
                  </span>
                </div>
              )}

              <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
                {contentLoading ? (
                  <div className="py-10 text-center text-[13px] text-[var(--text-muted)]">
                    正在读取文件内容...
                  </div>
                ) : !contentData || contentData.content.trim().length === 0 ? (
                  <div className="py-10 text-center text-[13px] text-[var(--text-faint)]">
                    当前文件为空，可点击右上角「用记事本编辑」添加规则内容。
                  </div>
                ) : previewMode === "rendered" ? (
                  <MarkdownDocView text={contentData.content} onOpenUrl={onOpenUrl} />
                ) : (
                  <pre className="whitespace-pre-wrap break-words font-mono-code text-[12.5px] leading-relaxed text-[var(--text-primary)] select-text">
                    {contentData.content}
                  </pre>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
