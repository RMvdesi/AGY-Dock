import type { StorageInventory, StorageNode } from "../types/ipc";
import { basename } from "./format";

export function canDrillStorageNode(node: StorageNode) {
  return Boolean(node.lazyChildren || node.children.length);
}

const projectNodeDefaults = {
  category: "other",
  path: "",
  subtitle: "",
  deletability: "caution",
  deletabilityLabel: "",
  protected: false,
  sessionId: "",
  mtime: 0,
  isArchived: false,
  isUnnamed: false,
  isSubagent: false,
  deleteTargets: [],
};

function projectPathKey(path: string) {
  return path.toLowerCase().replaceAll("/", "\\").replace(/\\+$/, "");
}

export function buildProjectStorageTree(
  inventory: StorageInventory,
  query: string,
  activeProjectId: string | null,
  activeTree: StorageNode | null,
): StorageNode {
  const folders = new Map<string, StorageNode>();
  for (const project of inventory.projects) {
    for (const folder of project.folders) {
      const pathKey = projectPathKey(folder.path);
      if (folders.has(pathKey)) continue;
      const nodeId = `project:root:${folder.path}`;
      const canRead = folder.status !== "unavailable";
      const loaded = nodeId === activeProjectId ? activeTree : null;
      const children = loaded?.children ?? folder.preview ?? [];
      folders.set(pathKey, {
        ...projectNodeDefaults,
        nodeId,
        name: project.folders.length > 1 ? basename(folder.path) : project.name,
        kind: "project",
        category: "code",
        path: folder.path,
        subtitle: project.folders.length > 1 ? `${folder.path} · ${project.name}` : folder.path,
        purposeDesc: canRead ? "可清理整个项目目录，或展开后选择其中的文件。" : "项目目录暂时无法读取。",
        deletabilityLabel: folder.status === "partial" ? "部分可读" : canRead ? "项目目录" : "不可访问",
        sizeBytes: loaded?.sizeBytes ?? folder.sizeBytes,
        fileCount: loaded?.fileCount ?? folder.fileCount,
        mtime: folder.mtime,
        lazyChildren: canRead && !loaded,
        projectRootPath: canRead ? folder.path : undefined,
        deleteTargets: canRead ? [folder.path] : [],
        manuallyAdded: project.source === "manual",
        children: children.map((node) => ({
          ...node,
          projectRootPath: folder.path,
          lazyChildren: !loaded && node.kind === "dir",
        })),
      });
    }
  }

  const term = activeProjectId ? "" : query.trim().toLowerCase();
  const children = [...folders.values()]
    .filter((node) => !term || `${node.name} ${node.subtitle}`.toLowerCase().includes(term))
    .sort((a, b) => b.sizeBytes - a.sizeBytes || a.name.localeCompare(b.name));
  let sizeBytes = inventory.projectsUsage.sizeBytes;
  let fileCount = inventory.projectsUsage.fileCount;
  if (term) {
    const roots: string[] = [];
    sizeBytes = 0;
    fileCount = 0;
    for (const folder of [...children].sort((a, b) => a.path.length - b.path.length)) {
      const key = projectPathKey(folder.path);
      if (roots.some((root) => key.startsWith(`${root}\\`))) continue;
      roots.push(key);
      sizeBytes += folder.sizeBytes;
      fileCount += folder.fileCount;
    }
  }

  return {
    ...projectNodeDefaults,
    nodeId: "root:projects",
    name: "项目文件",
    kind: "root",
    purposeDesc: "所有已发现和手动添加的项目目录，重叠路径在合计中只计一次。",
    sizeBytes,
    fileCount,
    children,
  };
}
