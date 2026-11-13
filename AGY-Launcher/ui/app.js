const THEME_STORAGE_KEY = 'agy-manager-theme';
const THEMES = ['auto', 'light', 'dark'];
const THEME_LABELS = { auto: '自动', light: '浅色', dark: '深色' };

const isSidecarMode = () => Boolean(window.sidecar && typeof window.sidecar.fetch === 'function');

function getManagerToken() {
  const meta = document.querySelector('meta[name="agy-manager-token"]');
  return meta ? meta.getAttribute('content') || '' : '';
}

async function apiGet(path) {
  if (isSidecarMode()) {
    const res = await window.sidecar.fetch(path, { method: 'GET' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
    return data;
  }
  const res = await fetch(path, { method: 'GET', cache: 'no-store' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

async function apiPost(path, payload = {}) {
  if (isSidecarMode()) {
    const res = await window.sidecar.fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
    return data;
  }
  const headers = { 'Content-Type': 'application/json' };
  const token = getManagerToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatBytes(bytes) {
  const num = Number(bytes) || 0;
  if (num < 1024) return `${num} B`;
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
  return `${(num / (1024 * 1024)).toFixed(2)} MB`;
}

function splitArgsText(text) {
  const lines = String(text || '').trim();
  if (!lines) return [];
  if (lines.includes('\n')) {
    return lines
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return lines.match(/"[^"]*"|'[^']*'|\S+/g)?.map((tok) => tok.replace(/^["']|["']$/g, '')) || [];
}

const state = {
  overview: null,
  nativePlugins: [],
  activeTab: 'external',
  nativeSearch: '',
  selectedLogId: 'launcher',
  logTail: 200,
  logStreaming: true,
  eventSource: null,
  logPollTimer: null,
  overviewTimer: null,
  pluginModalMode: 'create',
  pendingDeleteId: null,
};

const els = {
  runtimeBadge: document.getElementById('runtime-mode-badge'),
  themeToggleBtn: document.getElementById('theme-toggle-btn'),
  themeLabel: document.getElementById('theme-label'),
  refreshBtn: document.getElementById('refresh-btn'),
  createShortcutsBtn: document.getElementById('create-shortcuts-btn'),
  dockAttachBtn: document.getElementById('dock-attach-btn'),
  quickLaunchState: document.getElementById('quick-launch-state'),
  quickLaunchDesc: document.getElementById('quick-launch-desc'),
  primaryLaunchBtn: document.getElementById('primary-launch-btn'),
  primaryLaunchLabel: document.getElementById('primary-launch-label'),
  bannerAlert: document.getElementById('banner-alert'),

  metricClientPill: document.getElementById('metric-client-pill'),
  metricClientValue: document.getElementById('metric-client-value'),
  metricClientSub: document.getElementById('metric-client-sub'),
  metricCdpPill: document.getElementById('metric-cdp-pill'),
  metricCdpValue: document.getElementById('metric-cdp-value'),
  metricCdpSub: document.getElementById('metric-cdp-sub'),
  metricExternalPill: document.getElementById('metric-external-pill'),
  metricExternalValue: document.getElementById('metric-external-value'),
  metricExternalSub: document.getElementById('metric-external-sub'),
  metricIntegrityPill: document.getElementById('metric-integrity-pill'),
  metricNativeValue: document.getElementById('metric-native-value'),
  metricNativeSub: document.getElementById('metric-native-sub'),

  tabCountExternal: document.getElementById('tab-count-external'),
  tabCountNative: document.getElementById('tab-count-native'),
  externalGrid: document.getElementById('external-plugins-grid'),
  nativeList: document.getElementById('native-plugins-list'),
  nativeSearchInput: document.getElementById('native-search-input'),

  attachEnabledBtn: document.getElementById('attach-enabled-btn'),
  stopAllBtn: document.getElementById('stop-all-btn'),
  addPluginBtn: document.getElementById('add-plugin-btn'),

  logSourceSelect: document.getElementById('log-source-select'),
  logTailSelect: document.getElementById('log-tail-select'),
  logStreamToggleBtn: document.getElementById('log-stream-toggle-btn'),
  logClearBtn: document.getElementById('log-clear-btn'),
  logStreamStatus: document.getElementById('log-stream-status'),
  logPathLabel: document.getElementById('log-path-label'),
  logBytesLabel: document.getElementById('log-bytes-label'),
  logOutput: document.getElementById('log-output'),

  proxyForm: document.getElementById('proxy-form'),
  proxyEnabled: document.getElementById('proxy-enabled'),
  proxyHttp: document.getElementById('proxy-http'),
  proxyHttps: document.getElementById('proxy-https'),
  proxyAll: document.getElementById('proxy-all'),
  proxyElectron: document.getElementById('proxy-electron'),
  proxyDetectBtn: document.getElementById('proxy-detect-btn'),
  proxyDetectStatus: document.getElementById('proxy-detect-status'),

  pluginDialog: document.getElementById('plugin-dialog'),
  pluginForm: document.getElementById('plugin-form'),
  pluginDialogTitle: document.getElementById('plugin-dialog-title'),
  pluginDialogClose: document.getElementById('plugin-dialog-close'),
  pluginDialogCancel: document.getElementById('plugin-dialog-cancel'),
  fieldPluginId: document.getElementById('field-plugin-id'),
  fieldPluginName: document.getElementById('field-plugin-name'),
  fieldPluginDesc: document.getElementById('field-plugin-desc'),
  fieldPluginType: document.getElementById('field-plugin-type'),
  fieldPluginCommand: document.getElementById('field-plugin-command'),
  fieldPluginLaunchArgs: document.getElementById('field-plugin-launch-args'),
  fieldPluginAttachArgs: document.getElementById('field-plugin-attach-args'),
  fieldPluginHealth: document.getElementById('field-plugin-health'),
  fieldPluginMatch: document.getElementById('field-plugin-match'),
  fieldPluginEnabled: document.getElementById('field-plugin-enabled'),
  fieldPluginAutoAttach: document.getElementById('field-plugin-auto-attach'),

  deleteDialog: document.getElementById('delete-dialog'),
  deleteForm: document.getElementById('delete-form'),
  deleteDialogClose: document.getElementById('delete-dialog-close'),
  deleteDialogCancel: document.getElementById('delete-dialog-cancel'),
  deleteDialogMessage: document.getElementById('delete-dialog-message'),

  toastRegion: document.getElementById('toast-region'),
};

function showToast(message, tone = 'ok') {
  const node = document.createElement('div');
  node.className = `toast-item ${tone === 'error' ? 'is-error' : 'is-ok'}`;
  node.textContent = message;
  els.toastRegion.appendChild(node);
  setTimeout(() => {
    node.remove();
  }, 3600);
}

function applyTheme(theme) {
  const next = THEMES.includes(theme) ? theme : 'auto';
  if (next === 'auto') {
    document.documentElement.removeAttribute('data-theme');
  } else {
    document.documentElement.setAttribute('data-theme', next);
  }
  els.themeLabel.textContent = THEME_LABELS[next];
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // Ignore storage error in restricted frames
  }
}

function initTheme() {
  let saved = 'auto';
  try {
    saved = localStorage.getItem(THEME_STORAGE_KEY) || 'auto';
  } catch {
    saved = 'auto';
  }
  applyTheme(saved);
  els.themeToggleBtn.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme') || 'auto';
    const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
    applyTheme(next);
  });
}

function setPill(el, tone, text) {
  el.className = `pill pill-${tone}`;
  el.textContent = text;
}

function renderOverview() {
  const ov = state.overview;
  if (!ov) return;

  if (ov.managerOffline) {
    els.bannerAlert.hidden = false;
    els.bannerAlert.innerHTML =
      '后台守护进程尚未启动或连接断开。<button id="ensure-daemon-btn" type="button" class="btn btn-sm btn-secondary" style="margin-left:8px;">立即唤醒守护服务</button>';
    const btn = document.getElementById('ensure-daemon-btn');
    if (btn) btn.addEventListener('click', ensureManagerRunning);
  } else {
    els.bannerAlert.hidden = true;
  }

  const cdp = ov.cdp || {};
  const mainCount = Number(cdp.mainProcessCount || 0);
  const sidecarCount = Number(cdp.sidecarProcessCount || 0);

  if (mainCount > 0) {
    setPill(els.metricClientPill, 'ok', '运行中');
    els.metricClientValue.textContent = `${mainCount} 主窗口`;
    els.metricClientSub.textContent = `Sidecar ${sidecarCount} · 进程总数 ${cdp.processCount || 0}`;
  } else if (sidecarCount > 0) {
    setPill(els.metricClientPill, 'warn', '仅后台');
    els.metricClientValue.textContent = '主窗口未开';
    els.metricClientSub.textContent = `检测到 ${sidecarCount} 个驻留 Sidecar 进程`;
  } else {
    setPill(els.metricClientPill, 'muted', '未启动');
    els.metricClientValue.textContent = '离线';
    els.metricClientSub.textContent = ov.antigravityExists ? '已就绪，点击右上角启动' : '未定位 Antigravity.exe';
  }

  if (cdp.ready) {
    setPill(els.metricCdpPill, 'ok', '已就绪');
    els.metricCdpValue.textContent = `127.0.0.1:${cdp.port}`;
    els.metricCdpSub.textContent = 'DevToolsActivePort 已验证监听';
    setPill(els.quickLaunchState, 'ok', '已运行 · 可一键唤醒');
    els.quickLaunchDesc.textContent = `Antigravity 正在运行 (CDP :${cdp.port})，点击将窗口置前并确保全部启用插件处于挂载状态。`;
    els.primaryLaunchLabel.textContent = '唤醒 AGY 并附着插件';
  } else {
    setPill(els.metricCdpPill, mainCount > 0 ? 'warn' : 'muted', mainCount > 0 ? '待就绪' : '未监听');
    els.metricCdpValue.textContent = cdp.port ? `:${cdp.port}` : '无端口';
    els.metricCdpSub.textContent = cdp.reason || '等待启动 Antigravity';
    setPill(els.quickLaunchState, mainCount > 0 ? 'warn' : 'muted', mainCount > 0 ? '连接就绪中' : '等待启动');
    els.quickLaunchDesc.textContent = '点击一键静默启动 Antigravity 客户端，并自动加载所有已启用的外部托管插件。';
    els.primaryLaunchLabel.textContent = '快捷启动 Antigravity';
  }

  const plugins = ov.plugins || [];
  const runningPlugins = plugins.filter((p) => p.running);
  const enabledPlugins = plugins.filter((p) => p.enabled !== false);
  setPill(
    els.metricExternalPill,
    runningPlugins.length > 0 ? 'ok' : 'muted',
    `${runningPlugins.length} / ${plugins.length} 运行`
  );
  els.metricExternalValue.textContent = `${runningPlugins.length} 个活跃`;
  els.metricExternalSub.textContent = `已启用 ${enabledPlugins.length} 个 · 总托管 ${plugins.length} 个`;
  els.tabCountExternal.textContent = String(plugins.length);

  if (ov.versionDllExists) {
    setPill(els.metricIntegrityPill, 'warn', '含 version.dll');
  } else {
    setPill(els.metricIntegrityPill, 'ok', '安装目录纯净');
  }

  renderExternalPlugins(plugins);
  syncProxyForm(ov.proxy || {});
  syncLogSources(plugins);
}

function renderExternalPlugins(plugins) {
  if (!plugins.length) {
    els.externalGrid.innerHTML =
      '<div class="empty-state">暂无托管的外部插件，点击右上角「+ 添加插件」新建配置。</div>';
    return;
  }

  els.externalGrid.innerHTML = plugins
    .map((p) => {
      const enabled = p.enabled !== false;
      const statusTone = p.running ? 'ok' : enabled ? 'muted' : 'warn';
      const statusText = p.running
        ? `● 运行中 (${p.pids?.length ? `PID ${p.pids.join(', ')}` : 'Health OK'})`
        : enabled
          ? '○ 未运行'
          : '⏸ 已禁用';

      const healthSummary = p.health
        ? `健康接口正常${p.health.port ? ` :${p.health.port}` : ''}`
        : p.healthUrl
          ? '未检测到健康端口'
          : '无健康端点';

      return `
        <article class="plugin-card" data-plugin-id="${escapeHtml(p.id)}">
          <div>
            <div class="plugin-card-head">
              <div class="plugin-title-wrap">
                <div class="plugin-name-row">
                  <h3 class="plugin-name">${escapeHtml(p.name || p.id)}</h3>
                  <span class="plugin-id-tag">${escapeHtml(p.id)}</span>
                  ${p.version ? `<span class="plugin-id-tag">v${escapeHtml(String(p.version).replace(/^v/i, ''))}</span>` : ''}
                </div>
                <p class="plugin-desc">${escapeHtml(p.description || '外部 CDP 托管插件')}</p>
              </div>
              <label class="switch" title="${enabled ? '点击禁用自动托管' : '点击启用托管'}">
                <input type="checkbox" class="js-toggle-plugin" data-id="${escapeHtml(p.id)}" ${enabled ? 'checked' : ''}>
                <span class="switch-track"></span>
              </label>
            </div>
          </div>

          <div class="plugin-meta">
            <span class="pill pill-${statusTone}">${escapeHtml(statusText)}</span>
            <span class="meta-chip mono">${escapeHtml(p.type || 'custom-cdp')}</span>
            <span class="meta-chip">${escapeHtml(healthSummary)}</span>
            <span class="meta-chip">${p.executableExists === false ? '⚠ 命令路径不存在' : '✓ 启动命令就绪'}</span>
          </div>

          <div class="plugin-card-foot">
            <div class="plugin-actions">
              <button type="button" class="btn btn-sm btn-primary js-plugin-action" data-id="${escapeHtml(p.id)}" data-action="start">启动</button>
              <button type="button" class="btn btn-sm btn-secondary js-plugin-action" data-id="${escapeHtml(p.id)}" data-action="restart">重启</button>
              <button type="button" class="btn btn-sm btn-secondary js-plugin-action" data-id="${escapeHtml(p.id)}" data-action="stop" ${p.running ? '' : 'disabled'}>停止</button>
            </div>
            <div class="plugin-actions">
              <button type="button" class="btn btn-sm btn-ghost js-open-log" data-id="${escapeHtml(p.id)}">日志</button>
              <button type="button" class="btn btn-sm btn-ghost js-edit-plugin" data-id="${escapeHtml(p.id)}">编辑</button>
              <button type="button" class="btn btn-sm btn-ghost js-delete-plugin" data-id="${escapeHtml(p.id)}">移除</button>
            </div>
          </div>
        </article>
      `;
    })
    .join('');
}

function renderNativePlugins() {
  const all = state.nativePlugins || [];
  const enabledCount = all.filter((p) => p.enabled).length;
  els.tabCountNative.textContent = String(all.length);
  els.metricNativeValue.textContent = `${enabledCount} / ${all.length} 启用`;

  const q = state.nativeSearch.trim().toLowerCase();
  const filtered = q
    ? all.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          p.dir.toLowerCase().includes(q) ||
          (p.description || '').toLowerCase().includes(q)
      )
    : all;

  if (!filtered.length) {
    els.nativeList.innerHTML = '<div class="empty-state">未匹配到符合条件的原生插件。</div>';
    return;
  }

  els.nativeList.innerHTML = filtered
    .map((p) => {
      const sidecarChip =
        p.sidecars && p.sidecars.length > 0
          ? `<span class="meta-chip">Sidecar: ${escapeHtml(p.sidecars.map((s) => s.displayName || s.id).join(', '))}</span>`
          : '';
      return `
        <article class="native-card">
          <div class="native-card-top">
            <div>
              <h3 class="native-card-title">${escapeHtml(p.name)} <span class="plugin-id-tag">v${escapeHtml(p.version)}</span></h3>
            </div>
            <span class="pill ${p.enabled ? 'pill-ok' : 'pill-muted'}">${p.enabled ? '✓ 已启用' : '○ 已禁用'}</span>
          </div>
          <p class="native-card-desc">${escapeHtml(p.description || '无描述信息')}</p>
          <div class="native-badges">
            <span class="meta-chip mono">${escapeHtml(p.dir)}</span>
            <span class="meta-chip">Skills: ${Number(p.skillCount || 0)}</span>
            ${p.hasMcp ? '<span class="meta-chip">MCP</span>' : ''}
            ${p.hasRules ? '<span class="meta-chip">Rules</span>' : ''}
            ${sidecarChip}
          </div>
        </article>
      `;
    })
    .join('');
}

function syncProxyForm(proxy) {
  if (document.activeElement && els.proxyForm.contains(document.activeElement)) return;
  els.proxyEnabled.checked = Boolean(proxy.enabled);
  els.proxyHttp.value = proxy.httpProxy || '';
  els.proxyHttps.value = proxy.httpsProxy || '';
  els.proxyAll.value = proxy.allProxy || '';
  els.proxyElectron.value = proxy.electronProxyServer || '';
}

function syncLogSources(plugins) {
  const prev = els.logSourceSelect.value || 'launcher';
  const options = [{ id: 'launcher', label: 'launcher.log (主控日志)' }];
  for (const p of plugins) {
    options.push({ id: p.id, label: `${p.id}.out.log (标准输出)` });
    options.push({ id: `${p.id}.err`, label: `${p.id}.err.log (错误输出)` });
  }
  const html = options
    .map((o) => `<option value="${escapeHtml(o.id)}">${escapeHtml(o.label)}</option>`)
    .join('');
  if (els.logSourceSelect.innerHTML !== html) {
    els.logSourceSelect.innerHTML = html;
  }
  if (options.some((o) => o.id === prev)) {
    els.logSourceSelect.value = prev;
  }
}

async function fetchOverview() {
  try {
    state.overview = await apiGet('/api/overview');
    renderOverview();
  } catch (err) {
    showToast(`刷新状态失败: ${err.message}`, 'error');
  }
}

async function fetchNativePlugins() {
  try {
    const data = await apiGet('/api/native-plugins');
    state.nativePlugins = Array.isArray(data.plugins) ? data.plugins : [];
    renderNativePlugins();
  } catch (err) {
    els.nativeList.innerHTML = `<div class="empty-state">读取原生插件失败: ${escapeHtml(err.message)}</div>`;
  }
}

async function ensureManagerRunning() {
  try {
    await apiPost('/api/manager/ensure', {});
    showToast('守护服务已唤醒');
    await Promise.all([fetchOverview(), fetchNativePlugins()]);
  } catch (err) {
    showToast(`唤醒失败: ${err.message}`, 'error');
  }
}

function applyLogPayload(data) {
  els.logPathLabel.textContent = data.path || '';
  els.logBytesLabel.textContent = formatBytes(data.bytes || 0);
  const text = data.content && data.content.trim() ? data.content : '暂无日志输出。';
  const nearBottom =
    els.logOutput.scrollHeight - els.logOutput.scrollTop - els.logOutput.clientHeight < 48;
  els.logOutput.textContent = text;
  if (nearBottom) {
    els.logOutput.scrollTop = els.logOutput.scrollHeight;
  }
}

async function loadLogOnce() {
  try {
    const qs = new URLSearchParams({
      id: state.selectedLogId,
      tail: String(state.logTail),
    });
    const data = await apiGet(`/api/logs?${qs}`);
    applyLogPayload(data);
  } catch (err) {
    els.logOutput.textContent = `加载日志失败: ${err.message}`;
  }
}

function stopLogStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  if (state.logPollTimer) {
    clearInterval(state.logPollTimer);
    state.logPollTimer = null;
  }
}

function startLogStream() {
  stopLogStream();
  if (!state.logStreaming || state.activeTab !== 'logs') {
    setPill(els.logStreamStatus, 'muted', '已暂停');
    return;
  }

  const qs = new URLSearchParams({
    id: state.selectedLogId,
    tail: String(state.logTail),
  });

  if (!isSidecarMode() && typeof EventSource === 'function') {
    setPill(els.logStreamStatus, 'ok', 'SSE 实时推送');
    const es = new EventSource(`/api/logs/stream?${qs}`);
    es.onmessage = (event) => {
      try {
        applyLogPayload(JSON.parse(event.data));
      } catch {
        // Ignore malformed SSE line
      }
    };
    es.onerror = () => {
      setPill(els.logStreamStatus, 'warn', '连接重连中');
    };
    state.eventSource = es;
  } else {
    setPill(els.logStreamStatus, 'ok', '轮询同步中');
    loadLogOnce();
    state.logPollTimer = setInterval(loadLogOnce, 1800);
  }
}

function switchTab(tabName) {
  state.activeTab = tabName;
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    const active = btn.dataset.tab === tabName;
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('.tab-panel').forEach((panel) => {
    panel.hidden = panel.id !== `panel-${tabName}`;
  });
  if (tabName === 'logs') {
    startLogStream();
  } else {
    stopLogStream();
  }
}

function openPluginDialog(mode, plugin = null) {
  state.pluginModalMode = mode;
  els.pluginForm.reset();

  if (mode === 'edit' && plugin) {
    els.pluginDialogTitle.textContent = `编辑插件 · ${plugin.name || plugin.id}`;
    els.fieldPluginId.value = plugin.id;
    els.fieldPluginId.readOnly = true;
    els.fieldPluginName.value = plugin.name || '';
    els.fieldPluginDesc.value = plugin.description || '';
    els.fieldPluginType.value = plugin.type || 'custom-cdp';
    els.fieldPluginCommand.value = plugin.command || '';
    els.fieldPluginLaunchArgs.value = (plugin.launchArgs || []).join('\n');
    els.fieldPluginAttachArgs.value = (plugin.attachArgs || []).join('\n');
    els.fieldPluginHealth.value = plugin.healthUrl || '';
    els.fieldPluginMatch.value = plugin.processMatch || '';
    els.fieldPluginEnabled.checked = plugin.enabled !== false;
    els.fieldPluginAutoAttach.checked = plugin.autoAttach !== false;
  } else {
    els.pluginDialogTitle.textContent = '添加外部托管插件';
    els.fieldPluginId.readOnly = false;
    els.fieldPluginEnabled.checked = true;
    els.fieldPluginAutoAttach.checked = true;
  }

  els.pluginDialog.showModal();
}

function openDeleteDialog(id) {
  state.pendingDeleteId = id;
  els.deleteDialogMessage.textContent = `确定从 plugins.json 移除「${id}」并停止其关联进程吗？磁盘上的源码或可执行文件不会被删除。`;
  els.deleteDialog.showModal();
}

function wireEvents() {
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  els.refreshBtn.addEventListener('click', async () => {
    await Promise.all([fetchOverview(), fetchNativePlugins()]);
    showToast('状态已刷新');
  });

  els.createShortcutsBtn.addEventListener('click', async () => {
    els.createShortcutsBtn.disabled = true;
    try {
      await apiPost('/api/shortcuts/create', {});
      showToast('已生成桌面图标：AGY Plugin Manager 与 Antigravity');
    } catch (err) {
      showToast(`生成桌面图标失败: ${err.message}`, 'error');
    } finally {
      els.createShortcutsBtn.disabled = false;
    }
  });

  els.primaryLaunchBtn.addEventListener('click', async () => {
    const ready = Boolean(state.overview?.cdp?.ready);
    els.primaryLaunchBtn.disabled = true;
    try {
      await apiPost('/api/antigravity/quick-launch', {});
      showToast(ready ? '已唤醒 Antigravity 并完成插件热附着' : '已启动 Antigravity 并加载托管插件');
      await fetchOverview();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      els.primaryLaunchBtn.disabled = false;
    }
  });

  const runAttachOnly = async (triggerBtn) => {
    triggerBtn.disabled = true;
    try {
      await apiPost('/api/antigravity/attach', {});
      showToast('已向所有启用插件下发热附着指令');
      await fetchOverview();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      triggerBtn.disabled = false;
    }
  };

  els.dockAttachBtn.addEventListener('click', () => runAttachOnly(els.dockAttachBtn));
  els.attachEnabledBtn.addEventListener('click', () => runAttachOnly(els.attachEnabledBtn));

  els.stopAllBtn.addEventListener('click', async () => {
    els.stopAllBtn.disabled = true;
    try {
      const data = await apiPost('/api/plugins/stop-all', {});
      if (data.overview) {
        state.overview = data.overview;
        renderOverview();
      }
      showToast('已停止全部外部托管插件');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      els.stopAllBtn.disabled = false;
    }
  });

  els.addPluginBtn.addEventListener('click', () => openPluginDialog('create'));

  els.externalGrid.addEventListener('change', async (e) => {
    const toggle = e.target.closest('.js-toggle-plugin');
    if (!toggle) return;
    const id = toggle.dataset.id;
    const enabled = toggle.checked;
    try {
      const data = await apiPost('/api/plugins/action', { id, action: 'toggle', enabled });
      if (data.overview) {
        state.overview = data.overview;
        renderOverview();
      }
      showToast(`${id} 已${enabled ? '启用' : '禁用'}`);
    } catch (err) {
      toggle.checked = !enabled;
      showToast(err.message, 'error');
    }
  });

  els.externalGrid.addEventListener('click', async (e) => {
    const actionBtn = e.target.closest('.js-plugin-action');
    if (actionBtn) {
      const { id, action } = actionBtn.dataset;
      actionBtn.disabled = true;
      try {
        const data = await apiPost('/api/plugins/action', { id, action });
        if (data.overview) {
          state.overview = data.overview;
          renderOverview();
        }
        const label = action === 'start' ? '已启动' : action === 'stop' ? '已停止' : '已重启';
        showToast(`${id} ${label}`);
      } catch (err) {
        showToast(err.message, 'error');
      } finally {
        actionBtn.disabled = false;
      }
      return;
    }

    const logBtn = e.target.closest('.js-open-log');
    if (logBtn) {
      state.selectedLogId = logBtn.dataset.id;
      els.logSourceSelect.value = state.selectedLogId;
      switchTab('logs');
      return;
    }

    const editBtn = e.target.closest('.js-edit-plugin');
    if (editBtn) {
      const plugin = (state.overview?.plugins || []).find((p) => p.id === editBtn.dataset.id);
      if (plugin) openPluginDialog('edit', plugin);
      return;
    }

    const delBtn = e.target.closest('.js-delete-plugin');
    if (delBtn) {
      openDeleteDialog(delBtn.dataset.id);
    }
  });

  els.nativeSearchInput.addEventListener('input', () => {
    state.nativeSearch = els.nativeSearchInput.value;
    renderNativePlugins();
  });

  els.logSourceSelect.addEventListener('change', () => {
    state.selectedLogId = els.logSourceSelect.value;
    startLogStream();
  });

  els.logTailSelect.addEventListener('change', () => {
    state.logTail = Number(els.logTailSelect.value || 200);
    startLogStream();
  });

  els.logStreamToggleBtn.addEventListener('click', () => {
    state.logStreaming = !state.logStreaming;
    els.logStreamToggleBtn.textContent = state.logStreaming ? '暂停跟踪' : '恢复跟踪';
    startLogStream();
  });

  els.logClearBtn.addEventListener('click', async () => {
    try {
      await apiPost('/api/logs/clear', { id: state.selectedLogId });
      els.logOutput.textContent = '暂无日志输出。';
      els.logBytesLabel.textContent = '0 B';
      showToast('日志已清空');
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  if (els.proxyDetectBtn) {
    els.proxyDetectBtn.addEventListener('click', async () => {
      els.proxyDetectBtn.disabled = true;
      try {
        const data = await apiPost('/api/proxy/detect', { save: true });
        const detection = data.detection || {};
        if (data.detected) {
          const proxy = data.proxy || detection;
          els.proxyEnabled.checked = true;
          els.proxyHttp.value = proxy.httpProxy || '';
          els.proxyHttps.value = proxy.httpsProxy || '';
          els.proxyAll.value = proxy.allProxy || '';
          els.proxyElectron.value = proxy.electronProxyServer || '';
          if (data.overview) {
            state.overview = data.overview;
            renderOverview();
          }
          const src = detection.processName
            ? `${detection.source || 'auto'}: ${detection.processName}`
            : (detection.source || 'auto');
          if (els.proxyDetectStatus) {
            els.proxyDetectStatus.textContent = `已自动配置 (${src})`;
          }
          showToast(`已自动配置 (${src})`);
        } else {
          if (els.proxyDetectStatus) {
            els.proxyDetectStatus.textContent = '未检测到活动系统或本地代理';
          }
          showToast('未检测到系统或本地代理', 'error');
        }
      } catch (err) {
        showToast(err.message, 'error');
      } finally {
        els.proxyDetectBtn.disabled = false;
      }
    });
  }

  els.proxyForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const data = await apiPost('/api/proxy/save', {
        proxy: {
          enabled: els.proxyEnabled.checked,
          httpProxy: els.proxyHttp.value.trim(),
          httpsProxy: els.proxyHttps.value.trim(),
          allProxy: els.proxyAll.value.trim(),
          electronProxyServer: els.proxyElectron.value.trim(),
        },
      });
      if (data.overview) {
        state.overview = data.overview;
        renderOverview();
      }
      showToast('代理配置已保存');
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  // Dialog lifecycle and returnValue reset
  els.pluginDialogClose.addEventListener('click', () => els.pluginDialog.close('cancel'));
  els.pluginDialogCancel.addEventListener('click', () => els.pluginDialog.close('cancel'));
  els.pluginDialog.addEventListener('close', () => {
    els.pluginDialog.returnValue = '';
  });

  els.pluginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      mode: state.pluginModalMode,
      plugin: {
        id: els.fieldPluginId.value.trim(),
        name: els.fieldPluginName.value.trim(),
        description: els.fieldPluginDesc.value.trim(),
        type: els.fieldPluginType.value,
        command: els.fieldPluginCommand.value.trim(),
        launchArgs: splitArgsText(els.fieldPluginLaunchArgs.value),
        attachArgs: splitArgsText(els.fieldPluginAttachArgs.value),
        healthUrl: els.fieldPluginHealth.value.trim() || undefined,
        processMatch: els.fieldPluginMatch.value.trim() || undefined,
        enabled: els.fieldPluginEnabled.checked,
        autoAttach: els.fieldPluginAutoAttach.checked,
      },
    };
    try {
      const data = await apiPost('/api/plugins/save', payload);
      if (data.overview) {
        state.overview = data.overview;
        renderOverview();
      }
      els.pluginDialog.close('saved');
      showToast(state.pluginModalMode === 'edit' ? '插件配置已更新' : '新插件已添加');
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  els.deleteDialogClose.addEventListener('click', () => els.deleteDialog.close('cancel'));
  els.deleteDialogCancel.addEventListener('click', () => els.deleteDialog.close('cancel'));
  els.deleteDialog.addEventListener('close', () => {
    els.deleteDialog.returnValue = '';
    state.pendingDeleteId = null;
  });

  els.deleteForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = state.pendingDeleteId;
    if (!id) return;
    try {
      const data = await apiPost('/api/plugins/delete', { id });
      if (data.overview) {
        state.overview = data.overview;
        renderOverview();
      }
      els.deleteDialog.close('deleted');
      showToast(`已移除插件 ${id}`);
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

async function bootstrap() {
  initTheme();
  els.runtimeBadge.textContent = isSidecarMode() ? 'Antigravity Sidecar' : 'Web 控制台';
  els.runtimeBadge.className = `pill ${isSidecarMode() ? 'pill-ok' : 'pill-muted'}`;

  wireEvents();

  await fetchOverview();
  if (isSidecarMode() && state.overview?.managerOffline) {
    await ensureManagerRunning();
  } else {
    await fetchNativePlugins();
  }

  state.overviewTimer = setInterval(fetchOverview, 5000);
}

bootstrap();
