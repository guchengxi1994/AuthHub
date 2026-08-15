const pages = {
  overview: '概览', authorize: '权限校验', users: '用户', organizations: '组织',
  roles: '角色', permissions: '权限', modules: '业务模块', resources: '资源', 'resource-instances': '资源实例', audit: '审计日志'
};
const resourceTypes = {
  api: 'API 接口', entity: '业务实体', mcp_server: 'MCP Server',
  mcp_tool: 'MCP Tool', page: '页面/路由', ui_action: 'UI 操作', ui_component: 'UI 组件', custom: '自定义资源'
};
const actions = ['view', 'read', 'create', 'update', 'delete', 'execute', 'manage'];
const actionLabels = {
  view: '查看', read: '读取', create: '创建', update: '更新',
  delete: '删除', execute: '执行', manage: '管理'
};
const resourceActions = {
  api: ['read', 'create', 'update', 'delete', 'execute', 'manage'],
  entity: ['view', 'read', 'create', 'update', 'delete', 'manage'],
  mcp_server: ['view', 'read', 'create', 'update', 'delete', 'manage'],
  mcp_tool: ['view', 'execute', 'manage'],
  page: ['view', 'manage'],
  ui_action: ['execute', 'manage'],
  ui_component: ['view', 'manage'],
  custom: actions
};
const state = { token: sessionStorage.getItem('authhub.token'), me: null, permissions: new Set(), page: 'overview' };
const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
const icon = (name, cls = '') => `<i data-lucide="${name}" class="${cls}"></i>`;
const refreshIcons = () => window.lucide && window.lucide.createIcons();
const badge = (label, type = 'muted') => `<span class="status status-${type}">${esc(label)}</span>`;
const status = enabled => enabled ? badge('启用', 'active') : badge('已停用', 'muted');
const button = (label, action, name, tone = 'icon') => tone === 'icon'
  ? `<button type="button" class="btn-icon" title="${esc(label)}" data-action="${esc(action)}">${icon(name)}</button>`
  : `<button type="button" class="btn-${tone}" data-action="${esc(action)}">${icon(name)}${esc(label)}</button>`;
const panel = (body, cls = '') => `<section class="surface ${cls}">${body}</section>`;
const empty = (text, action = '') => `<div class="flex min-h-[210px] flex-col items-center justify-center px-5 text-center"><div class="mb-3 grid h-10 w-10 place-items-center rounded-full bg-slate-100 text-slate-400">${icon('inbox')}</div><p class="text-sm text-slate-500">${esc(text)}</p>${action}</div>`;
const table = (headers, rows, emptyText = '暂无数据') => panel(`<div class="overflow-x-auto"><table class="data-table"><thead><tr>${headers.map(header => `<th>${header}</th>`).join('')}</tr></thead><tbody>${rows || `<tr><td colspan="${headers.length}">${empty(emptyText)}</td></tr>`}</tbody></table></div>`);
const pageHeader = (title, controls = '') => `<div class="mb-5 flex min-h-[34px] items-center justify-between gap-3"><h1 class="text-[22px] font-semibold leading-none text-slate-900">${esc(title)}</h1><div class="flex shrink-0 items-center gap-2">${controls}</div></div>`;
const resourceLabel = value => resourceTypes[value] || value || '-';
const actionLabel = value => actionLabels[value] || value || '-';
const managementPermission = (type, key, action) => `authhub:${type}:${key}:${action}`;
const can = (type, key, action) => Boolean(state.me?.is_super_admin || state.permissions.has(managementPermission(type, key, action)));
const pagePermission = {
  overview: ['page', 'admin', 'view'],
  authorize: ['page', 'admin', 'view'],
  users: ['entity', 'users', 'read'],
  organizations: ['entity', 'organizations', 'read'],
  roles: ['entity', 'roles', 'read'],
  permissions: ['entity', 'permissions', 'read'],
  modules: ['entity', 'modules', 'read'],
  resources: ['entity', 'resources', 'read'],
  'resource-instances': ['entity', 'resource-instances', 'read'],
  audit: ['entity', 'audit-events', 'read']
};
const canOpenPage = page => Boolean(pagePermission[page] && can(...pagePermission[page]));
const fallbackItems = { items: [] };
const allowedPage = () => Object.keys(pagePermission).find(canOpenPage) || '';

function applyNavigationPermissions() {
  $$('.nav-item').forEach(item => item.classList.toggle('hidden', !canOpenPage(item.dataset.page)));
}

function setToast(message, type = 'success') {
  const el = $('#toast');
  el.textContent = message;
  el.className = `pointer-events-none fixed bottom-5 right-5 z-50 max-w-sm rounded-lg border px-3 py-2 text-sm shadow-float ${type === 'error' ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-emerald-200 bg-white text-emerald-800'}`;
  clearTimeout(setToast.timer);
  setToast.timer = setTimeout(() => el.classList.add('hidden'), 3300);
}

function setNotice(message, type = 'error') {
  const el = $('#notice');
  el.innerHTML = `<div class="flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${type === 'error' ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}">${icon(type === 'error' ? 'circle-alert' : 'circle-check', 'mt-0.5 h-4 w-4 shrink-0')}<span>${esc(message)}</span></div>`;
  el.classList.remove('hidden');
  refreshIcons();
}

function clearNotice() { $('#notice').innerHTML = ''; $('#notice').classList.add('hidden'); }

async function loadRuntimeVersion() {
  const targets = $$('[data-runtime-version]');
  try {
    const response = await fetch('/api/meta', { cache: 'no-store' });
    if (!response.ok) throw new Error('metadata unavailable');
    const release = await response.json();
    const label = `v${release.version}${release.build ? ` · ${release.build}` : ''}`;
    targets.forEach(target => { target.textContent = label; });
  } catch (_) {
    targets.forEach(target => { target.textContent = '版本未知'; });
  }
}

async function api(path, options = {}) {
  const headers = { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  const body = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.message || body.code || `请求失败（${response.status}）`);
  return body;
}

function setLoading(element, loading, label) {
  element.disabled = loading;
  element.innerHTML = loading ? `${icon('loader-circle', 'animate-spin')}处理中…` : `${icon('check')}${esc(label)}`;
  refreshIcons();
}

function openModal(title, body, wide = false) {
  const el = $('#modal');
  el.className = `modal ${wide ? 'max-w-3xl' : ''}`;
  el.innerHTML = `<div class="flex h-14 items-center justify-between border-b border-slate-200 px-5"><h2 class="text-[15px] font-semibold text-slate-900">${esc(title)}</h2><button type="button" class="btn-icon" id="modal-close" title="关闭">${icon('x')}</button></div><div class="modal-body p-5">${body}</div>`;
  el.showModal();
  $('#modal-close').onclick = () => el.close();
  refreshIcons();
  return el;
}

function ask(title, message, confirmLabel = '确认删除') {
  return new Promise(resolve => {
    const el = $('#confirm-modal');
    el.innerHTML = `<div class="p-5"><div class="mb-3 flex h-9 w-9 items-center justify-center rounded-full bg-rose-50 text-rose-600">${icon('triangle-alert')}</div><h2 class="text-[15px] font-semibold text-slate-900">${esc(title)}</h2><p class="mt-2 text-sm leading-6 text-slate-500">${esc(message)}</p><div class="mt-6 flex justify-end gap-2"><button type="button" id="confirm-cancel" class="btn-secondary">取消</button><button type="button" id="confirm-yes" class="btn-danger">${esc(confirmLabel)}</button></div></div>`;
    el.showModal();
    $('#confirm-cancel').onclick = () => { el.close(); resolve(false); };
    $('#confirm-yes').onclick = () => { el.close(); resolve(true); };
    refreshIcons();
  });
}

function setPage(page) {
  if (!canOpenPage(page)) return;
  state.page = page;
  $('#shell-title').textContent = pages[page];
  $('#shell-context').textContent = 'AuthHub';
  $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.page === page));
  $('#sidebar').classList.remove('open');
  $('#sidebar-backdrop').classList.add('hidden');
  render();
}

function selectionList(items, inputName, selected = new Set(), value = item => item.id, text = item => item.name) {
  if (!items.length) return '<p class="selection-list-empty">暂无可选项</p>';
  return `<div class="selection-list">${items.map(item => `<label><input type="checkbox" name="${esc(inputName)}" value="${esc(value(item))}" ${selected.has(value(item)) ? 'checked' : ''}><span>${esc(text(item))}</span></label>`).join('')}</div>`;
}

function permissionGroups(permissions, modules, resources) {
  const moduleNames = Object.fromEntries(modules.map(item => [item.id, item.name]));
  const resourceById = Object.fromEntries(resources.map(item => [item.id, item]));
  const grouped = new Map();
  permissions.forEach(permission => {
    const resource = resourceById[permission.resource_id];
    const builtIn = permission.module_id === 'authhub' || String(permission.code || '').startsWith('authhub:');
    const moduleName = moduleNames[permission.module_id] || (builtIn ? 'AuthHub 内置' : '未归属模块');
    const resourceName = resource?.name || permission.resource_key || '通用操作';
    const resourceType = resource?.resource_type || permission.resource_type;
    const key = `${permission.module_id || 'system'}:${permission.resource_id || permission.code}`;
    if (!grouped.has(key)) grouped.set(key, { key, moduleId: permission.module_id || '', moduleName, resourceName, resourceType, builtIn, permissions: [] });
    grouped.get(key).permissions.push(permission);
  });
  return [...grouped.values()]
    .sort((left, right) => `${left.moduleName}/${left.resourceName}`.localeCompare(`${right.moduleName}/${right.resourceName}`, 'zh-CN'))
    .map(group => ({ ...group, permissions: group.permissions.sort((left, right) => left.name.localeCompare(right.name, 'zh-CN')) }));
}

function selectionToolbar(inputName) {
  return `<div class="selection-toolbar"><span>已选 <strong data-selected-count="${esc(inputName)}">0</strong></span><div><button type="button" class="btn-link" data-selection="all" data-selection-name="${esc(inputName)}">全选</button><button type="button" class="btn-link" data-selection="none" data-selection-name="${esc(inputName)}">清空</button><button type="button" class="btn-link" data-selection="invert" data-selection-name="${esc(inputName)}">反选</button></div></div>`;
}

function permissionSections(groups) {
  const modules = new Map();
  groups.forEach(group => {
    const key = group.moduleId || (group.builtIn ? 'authhub' : 'unassigned');
    if (!modules.has(key)) modules.set(key, { key, name: group.moduleName, groups: [] });
    modules.get(key).groups.push(group);
  });
  const sortedModules = [...modules.values()].sort((left, right) => left.name.localeCompare(right.name, 'zh-CN'));
  return [
    { key: 'authhub', label: 'AuthHub 内置权限', modules: sortedModules.filter(module => module.key === 'authhub') },
    { key: 'business', label: '业务系统权限', modules: sortedModules.filter(module => module.key !== 'authhub') }
  ].filter(section => section.modules.length);
}

function permissionOptions(groups, inputName, selectedCodes = new Set()) {
  if (!groups.length) return '<p class="selection-list-empty">当前资源还没有可分配的启用权限。</p>';
  const scopeLabels = { global: '全部', owner: '本人归属', organization: '组织归属' };
  const renderResource = group => {
    const selectedCount = group.permissions.filter(permission => selectedCodes.has(permission.code)).length;
    const enabledCount = group.permissions.filter(permission => permission.enabled).length;
    const enabledSelectedCount = group.permissions.filter(permission => permission.enabled && selectedCodes.has(permission.code)).length;
    const fullySelected = enabledCount > 0 && enabledCount === enabledSelectedCount;
    return `<details class="permission-group" data-permission-group ${selectedCount ? 'open' : ''}><summary class="permission-group-heading"><div><strong>${esc(group.resourceName)}</strong></div><div class="permission-group-meta"><span data-permission-group-selected>${selectedCount} / ${group.permissions.length}</span><small>${esc(resourceLabel(group.resourceType))}</small><label class="permission-group-select" title="选择此资源的全部启用权限"><input type="checkbox" data-permission-group-select ${fullySelected ? 'checked' : ''} ${enabledCount ? '' : 'disabled'}><span>全选</span></label><i data-lucide="chevron-down" aria-hidden="true"></i></div></summary><div class="permission-group-options">${group.permissions.map(permission => `<label class="permission-option"><input type="checkbox" name="${esc(inputName)}" value="${esc(permission.code)}" ${selectedCodes.has(permission.code) ? 'checked' : ''} ${permission.enabled ? '' : 'disabled'}><span><strong>${esc(permission.name)}</strong><small>${esc(actionLabel(permission.action))} · ${esc(scopeLabels[permission.scope || 'global'] || permission.scope || '全部')} · ${esc(permission.code)}</small></span>${permission.enabled ? '' : badge('停用', 'muted')}</label>`).join('')}</div></details>`;
  };
  return permissionSections(groups).map(section => {
    const permissionCount = section.modules.reduce((total, module) => total + module.groups.reduce((count, group) => count + group.permissions.length, 0), 0);
    return `<section class="permission-section" data-permission-section><div class="permission-section-heading"><strong>${esc(section.label)}</strong><small>${section.modules.length} 个模块 · ${permissionCount} 项</small></div>${section.modules.map(module => {
      const hasSelectedPermission = module.groups.some(group => group.permissions.some(permission => selectedCodes.has(permission.code)));
      const resourceCount = module.groups.length;
      const modulePermissionCount = module.groups.reduce((count, group) => count + group.permissions.length, 0);
      return `<details class="permission-module-group" data-permission-module-group ${hasSelectedPermission ? 'open' : ''}><summary><span>${esc(module.name)}</span><small>${resourceCount} 个资源 · ${modulePermissionCount} 项</small><i data-lucide="chevron-down" aria-hidden="true"></i></summary><div>${module.groups.map(renderResource).join('')}</div></details>`;
    }).join('')}</section>`;
  }).join('');
}

function updateSelectedCount(root, inputName) {
  const count = $$(`input[name="${inputName}"]:checked`, root).length;
  $$(`[data-selected-count="${inputName}"]`, root).forEach(item => { item.textContent = count; });
}

function updatePermissionGroupSelection(root, inputName) {
  $$('[data-permission-group]', root).forEach(group => {
    const permissions = $$(`input[name="${inputName}"]`, group);
    const enabledPermissions = permissions.filter(input => !input.disabled);
    const selectedCount = permissions.filter(input => input.checked).length;
    const selectedEnabledCount = enabledPermissions.filter(input => input.checked).length;
    $('[data-permission-group-selected]', group).textContent = `${selectedCount} / ${permissions.length}`;
    const control = $('[data-permission-group-select]', group);
    control.checked = enabledPermissions.length > 0 && selectedEnabledCount === enabledPermissions.length;
    control.indeterminate = selectedEnabledCount > 0 && selectedEnabledCount < enabledPermissions.length;
  });
}

function bindSelectionToolbar(root, inputName, onChange = () => {}) {
  const inputs = () => $$(`input[name="${inputName}"]`, root).filter(item => !item.disabled);
  const update = () => {
    updateSelectedCount(root, inputName);
    updatePermissionGroupSelection(root, inputName);
    onChange();
  };
  $$(`[data-selection-name="${inputName}"]`, root).forEach(control => {
    control.onclick = () => {
      const action = control.dataset.selection;
      inputs().forEach(input => { input.checked = action === 'all' ? true : action === 'none' ? false : !input.checked; });
      update();
    };
  });
  $$('[data-permission-group-select]', root).forEach(control => {
    control.onclick = event => {
      event.preventDefault();
      event.stopPropagation();
      control.checked = !control.checked;
      control.dispatchEvent(new Event('change'));
    };
    control.onchange = () => {
      $$(`input[name="${inputName}"]`, control.closest('[data-permission-group]')).filter(input => !input.disabled).forEach(input => { input.checked = control.checked; });
      update();
    };
  });
  inputs().forEach(input => { input.onchange = update; });
  update();
}

function filterPermissionOptions(root, query) {
  const normalizedQuery = query.trim().toLowerCase();
  $$('.permission-group', root).forEach(group => {
    $$('.permission-option', group).forEach(option => option.classList.toggle('hidden', !option.textContent.toLowerCase().includes(normalizedQuery)));
    const hasVisibleOption = Boolean($('.permission-option:not(.hidden)', group));
    group.classList.toggle('hidden', !hasVisibleOption);
    if (normalizedQuery && hasVisibleOption) group.open = true;
  });
  $$('[data-permission-module-group]', root).forEach(module => {
    const hasVisibleGroup = Boolean($('.permission-group:not(.hidden)', module));
    module.classList.toggle('hidden', !hasVisibleGroup);
    if (normalizedQuery && hasVisibleGroup) module.open = true;
  });
  $$('[data-permission-section]', root).forEach(section => section.classList.toggle('hidden', !$('.permission-module-group:not(.hidden)', section)));
}

function permissionDirectory(groups, scopeLabels) {
  const compact = groups.length > 4 || groups.reduce((total, group) => total + group.permissions.length, 0) > 18;
  return `<section class="permission-directory">${permissionSections(groups).map(section => `<section class="permission-section permission-directory-section" data-permission-directory-section><div class="permission-section-heading"><strong>${esc(section.label)}</strong><small>${section.modules.length} 个模块</small></div>${section.modules.map(module => `<details class="permission-directory-module" data-permission-directory-module ${compact ? '' : 'open'}><summary><span>${esc(module.name)}</span><small>${module.groups.length} 个资源 · ${module.groups.reduce((count, group) => count + group.permissions.length, 0)} 项</small><i data-lucide="chevron-down" aria-hidden="true"></i></summary><div>${module.groups.map(group => `<details class="permission-directory-group" data-permission-directory-group ${compact ? '' : 'open'}><summary><div><strong>${esc(group.resourceName)}</strong><span>${esc(resourceLabel(group.resourceType))}</span></div><div><small>${group.permissions.length} 项</small><i data-lucide="chevron-down" aria-hidden="true"></i></div></summary><div class="permission-directory-items">${group.permissions.map(permission => `<div class="permission-directory-item" data-permission-directory-item><div><strong>${esc(permission.name)}</strong><code>${esc(permission.code)}</code></div><div>${badge(actionLabel(permission.action), 'blue')}${badge(scopeLabels[permission.scope || 'global'] || permission.scope || '全部', permission.scope === 'global' ? 'muted' : 'active')}${status(permission.enabled)}</div></div>`).join('')}</div></details>`).join('')}</div></details>`).join('')}</section>`).join('')}</section>`;
}

function filterPermissionDirectory(root, query) {
  const normalizedQuery = query.trim().toLowerCase();
  $$('[data-permission-directory-group]', root).forEach(group => {
    $$('[data-permission-directory-item]', group).forEach(item => item.classList.toggle('hidden', !item.textContent.toLowerCase().includes(normalizedQuery)));
    const hasVisibleItem = Boolean($('[data-permission-directory-item]:not(.hidden)', group));
    group.classList.toggle('hidden', !hasVisibleItem);
    if (normalizedQuery && hasVisibleItem) group.open = true;
  });
  $$('[data-permission-directory-module]', root).forEach(module => {
    const hasVisibleGroup = Boolean($('.permission-directory-group:not(.hidden)', module));
    module.classList.toggle('hidden', !hasVisibleGroup);
    if (normalizedQuery && hasVisibleGroup) module.open = true;
  });
  $$('[data-permission-directory-section]', root).forEach(section => section.classList.toggle('hidden', !$('.permission-directory-module:not(.hidden)', section)));
}

async function renderOverview() {
  const [overview, audit] = await Promise.all([api('/api/admin/overview'), can('entity', 'audit-events', 'read') ? api('/api/audit-events?limit=8') : Promise.resolve(fallbackItems)]);
  const metrics = [['用户', overview.users, 'users', 'blue'], ['组织', overview.organizations, 'network', 'warning'], ['角色', overview.roles, 'key-round', 'active'], ['权限', overview.permissions, 'key-square', 'blue'], ['模块', overview.modules, 'boxes', 'warning'], ['资源', overview.resources, 'database-zap', 'active'], ['实例索引', overview.resource_instances, 'list-tree', 'blue']];
  const rows = audit.items.map(event => `<tr><td class="whitespace-nowrap text-xs text-slate-500">${esc(new Date(event.occurred_at).toLocaleString())}</td><td class="font-mono text-xs text-slate-700">${esc(event.action)}</td><td class="text-slate-500">${esc(event.target_type)} ${esc(event.target_id || '')}</td><td>${badge(event.outcome, event.outcome === 'success' || event.outcome === 'allowed' ? 'active' : 'danger')}</td></tr>`).join('');
  $('#content').innerHTML = pageHeader('概览', state.me.is_super_admin ? `${button('权限校验', 'goto:authorize', 'badge-check', 'secondary')}${button('新增业务模块', 'new-module', 'plus', 'primary')}` : '')
    + `<div class="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-7">${metrics.map(([label, value, name, tone]) => `<div class="surface min-w-0 px-4 py-3"><div class="flex items-center justify-between"><span class="text-xs font-medium text-slate-500">${label}</span><span class="grid h-7 w-7 place-items-center rounded-lg ${tone === 'active' ? 'bg-emerald-50 text-emerald-600' : tone === 'warning' ? 'bg-amber-50 text-amber-600' : 'bg-blue-50 text-blue-600'}">${icon(name, 'h-4 w-4')}</span></div><div class="mt-2 text-2xl font-semibold leading-none text-slate-900">${value}</div></div>`).join('')}</div>`
    + `<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]"><section class="surface overflow-hidden"><div class="flex h-12 items-center justify-between border-b border-slate-100 px-4"><h2 class="text-sm font-semibold text-slate-800">最近审计</h2><button type="button" class="text-sm font-medium text-brand-600 hover:text-brand-700" data-action="goto:audit">查看全部</button></div><div class="overflow-x-auto"><table class="data-table"><thead><tr><th>时间</th><th>动作</th><th>对象</th><th>结果</th></tr></thead><tbody>${rows || `<tr><td colspan="4">${empty('暂无审计记录')}</td></tr>`}</tbody></table></div></section><section class="surface p-4"><h2 class="text-sm font-semibold text-slate-800">配置入口</h2><div class="mt-3 divide-y divide-slate-100"><button type="button" data-action="goto:modules" class="overview-link"><span>${icon('boxes', 'h-4 w-4')} 新增业务模块</span>${icon('chevron-right', 'h-4 w-4')}</button><button type="button" data-action="goto:resources" class="overview-link"><span>${icon('database-zap', 'h-4 w-4')} 建立受控资源</span>${icon('chevron-right', 'h-4 w-4')}</button><button type="button" data-action="goto:permissions" class="overview-link"><span>${icon('key-square', 'h-4 w-4')} 配置资源操作权限</span>${icon('chevron-right', 'h-4 w-4')}</button></div></section></div>`;
  bindActions();
  refreshIcons();
}

async function renderAuthorize() {
  $('#content').innerHTML = pageHeader('权限校验') + panel(`<form id="check-form" class="grid gap-4 p-5 md:grid-cols-[1fr_1fr_auto]"><div><label class="label">权限标识 <span class="text-rose-600">*</span></label><input class="field" name="permission" required placeholder="由服务或 SDK 使用的权限编码"></div><div><label class="label">资源上下文</label><input class="field" name="resource" placeholder="可选，例如订单号或 Server 名称"></div><div class="self-end"><button class="btn-primary" type="submit">${icon('badge-check')}执行校验</button></div></form><div id="check-result" class="hidden border-t border-slate-100 px-5 py-4"></div>`);
  $('#check-form').onsubmit = async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const buttonEl = $('button[type="submit"]', event.currentTarget);
    try {
      setLoading(buttonEl, true, '执行校验');
      const result = await api('/api/auth/check', { method: 'POST', body: JSON.stringify({ permission: form.get('permission'), resource: form.get('resource') || undefined }) });
      const el = $('#check-result');
      el.classList.remove('hidden');
      el.innerHTML = `<div class="flex items-center justify-between"><span class="text-sm font-medium text-slate-800">校验结果</span>${result.allowed ? badge('允许', 'active') : badge(result.reason || '拒绝', result.authenticated ? 'danger' : 'warning')}</div>`;
    } catch (error) { setNotice(error.message); } finally { setLoading(buttonEl, false, '执行校验'); }
  };
  refreshIcons();
}

async function renderUsers() {
  const [users, organizations, roles] = await Promise.all([
    api('/api/users'),
    can('entity', 'organizations', 'read') ? api('/api/organizations') : Promise.resolve(fallbackItems),
    can('entity', 'roles', 'read') ? api('/api/roles') : Promise.resolve(fallbackItems)
  ]);
  const organizationNames = Object.fromEntries(organizations.items.map(item => [item.id, item.name]));
  const roleNames = Object.fromEntries(roles.items.map(item => [item.id, item.name]));
  const rows = users.items.map(user => {
    const assignedNames = (user.role_ids || []).map(id => roleNames[id] || id).join('、') || '-';
    const manageable = !user.is_super_admin || state.me.is_super_admin;
    const controls = [
      can('entity', 'users', 'update') && can('entity', 'organizations', 'read') && manageable ? button('配置组织', `user-organizations:${user.id}`, 'network') : '',
      can('entity', 'users', 'update') && can('entity', 'roles', 'read') && manageable ? button('配置角色', `user-roles:${user.id}`, 'key-round') : '',
      can('entity', 'users', 'update') && manageable ? button(user.enabled ? '停用' : '启用', `user-toggle:${user.id}:${!user.enabled}`, 'power') : ''
    ].join('');
    return `<tr data-user-row="${esc(user.id)}"><td><div class="font-medium text-slate-800">${esc(user.display_name || user.username)}</div><div class="mt-0.5 font-mono text-xs text-slate-500">${esc(user.username)}</div></td><td class="max-w-[220px] truncate text-slate-500">${(user.organization_ids || []).map(id => esc(organizationNames[id] || id)).join('、') || '-'}</td><td class="max-w-[220px] truncate text-slate-500">${esc(assignedNames)}</td><td>${user.is_super_admin ? badge('系统管理员', 'blue') : status(user.enabled)}</td><td><div class="flex justify-end gap-1">${controls}</div></td></tr>`;
  });
  const createUser = can('entity', 'users', 'create') && can('entity', 'organizations', 'read') && can('entity', 'roles', 'read');
  $('#content').innerHTML = pageHeader('用户', createUser ? button('新增用户', 'new-user', 'user-plus', 'primary') : '')
    + `<div class="mb-3 flex items-center justify-between"><div class="relative w-full max-w-xs">${icon('search', 'pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400')}<input id="user-filter" class="field pl-9" placeholder="筛选用户名、组织或角色"></div><span class="ml-3 whitespace-nowrap text-xs text-slate-500">${users.items.length} 个用户</span></div>`
    + table(['用户', '所属组织', '已分配角色', '状态', '操作'], rows.join(''), '暂无用户');
  $('#user-filter').oninput = event => {
    const value = event.target.value.toLowerCase();
    $$('[data-user-row]').forEach(row => row.classList.toggle('hidden', !row.textContent.toLowerCase().includes(value)));
  };
  bindActions();
  refreshIcons();
}

async function showNewUser() {
  const [roles, organizations] = await Promise.all([api('/api/roles'), api('/api/organizations')]);
  const el = openModal('新增用户', `<form id="new-user-form" class="space-y-5"><div class="grid gap-4 sm:grid-cols-2"><div><label class="label">用户名 <span class="text-rose-600">*</span></label><input class="field" name="username" required></div><div><label class="label">显示名称</label><input class="field" name="display_name"></div><div class="sm:col-span-2"><label class="label">初始密码 <span class="text-rose-600">*</span></label><input class="field" name="password" type="password" required></div></div><div><span class="label">所属组织</span>${selectionList(organizations.items, 'organization_ids')}</div><div><span class="label">初始角色</span>${selectionList(roles.items.filter(role => role.enabled), 'role_ids')}</div><div class="modal-footer"><button type="button" class="btn-secondary" id="form-cancel">取消</button><button class="btn-primary" type="submit">${icon('user-plus')}创建用户</button></div></form>`);
  $('#form-cancel', el).onclick = () => el.close();
  $('#new-user-form', el).onsubmit = async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const buttonEl = $('button[type="submit"]', event.currentTarget);
    try {
      setLoading(buttonEl, true, '创建用户');
      await api('/api/users', { method: 'POST', body: JSON.stringify({ username: form.get('username'), display_name: form.get('display_name'), password: form.get('password'), organization_ids: form.getAll('organization_ids'), role_ids: form.getAll('role_ids') }) });
      el.close(); setToast('用户已创建'); renderUsers();
    } catch (error) { setNotice(error.message); } finally { setLoading(buttonEl, false, '创建用户'); }
  };
}

async function showUserRoles(userId) {
  const [roles, assigned] = await Promise.all([api('/api/roles'), api(`/api/users/${userId}/roles`)]);
  const assignedIds = new Set(assigned.items.map(role => role.id));
  const el = openModal('配置用户角色', `<form id="user-roles-form" class="space-y-5"><div>${selectionList(roles.items.filter(role => role.enabled), 'role_ids', assignedIds)}</div><div class="modal-footer"><button type="button" class="btn-secondary" id="form-cancel">取消</button><button class="btn-primary" type="submit">${icon('save')}保存角色</button></div></form>`);
  $('#form-cancel', el).onclick = () => el.close();
  $('#user-roles-form', el).onsubmit = async event => {
    event.preventDefault();
    const selected = new Set(new FormData(event.currentTarget).getAll('role_ids'));
    const buttonEl = $('button[type="submit"]', event.currentTarget);
    try {
      setLoading(buttonEl, true, '保存角色');
      await Promise.all(roles.items.map(role => selected.has(role.id) === assignedIds.has(role.id) ? null : api(`/api/users/${userId}/roles/${role.id}`, { method: selected.has(role.id) ? 'POST' : 'DELETE' })));
      el.close(); setToast('用户角色已更新'); renderUsers();
    } catch (error) { setNotice(error.message); } finally { setLoading(buttonEl, false, '保存角色'); }
  };
}

async function showUserOrganizations(userId) {
  const [organizations, assigned] = await Promise.all([api('/api/organizations'), api(`/api/users/${userId}/organizations`)]);
  const assignedIds = new Set(assigned.items.map(organization => organization.id));
  const el = openModal('配置用户组织', `<form id="user-organizations-form" class="space-y-5"><div>${selectionList(organizations.items.filter(org => org.enabled), 'organization_ids', assignedIds)}</div><div class="modal-footer"><button type="button" class="btn-secondary" id="form-cancel">取消</button><button class="btn-primary" type="submit">${icon('save')}保存组织</button></div></form>`);
  $('#form-cancel', el).onclick = () => el.close();
  $('#user-organizations-form', el).onsubmit = async event => {
    event.preventDefault();
    const selected = new Set(new FormData(event.currentTarget).getAll('organization_ids'));
    const buttonEl = $('button[type="submit"]', event.currentTarget);
    try {
      setLoading(buttonEl, true, '保存组织');
      await Promise.all(organizations.items.map(org => selected.has(org.id) === assignedIds.has(org.id) ? null : api(`/api/users/${userId}/organizations/${org.id}`, { method: selected.has(org.id) ? 'POST' : 'DELETE' })));
      el.close(); setToast('用户组织已更新'); renderUsers();
    } catch (error) { setNotice(error.message); } finally { setLoading(buttonEl, false, '保存组织'); }
  };
}

async function renderOrganizations() {
  const data = await api('/api/organizations');
  const flatten = (items, depth = 0) => items.flatMap(item => [[item, depth], ...flatten(item.children || [], depth + 1)]);
  const rows = flatten(data.tree).map(([org, depth]) => `<tr><td><div class="flex items-center" style="padding-left:${depth * 20}px">${depth ? '<span class="mr-2 text-slate-300">└</span>' : ''}<span class="font-medium text-slate-800">${esc(org.name)}</span></div></td><td class="text-slate-500">${esc(org.description || '-')}</td><td>${status(org.enabled)}</td><td><div class="flex justify-end">${can('entity', 'organizations', 'update') ? button('编辑', `org-edit:${org.id}`, 'pencil') : ''}</div></td></tr>`).join('');
  state.organizations = data.items;
  $('#content').innerHTML = pageHeader('组织', can('entity', 'organizations', 'create') ? button('新增组织', 'new-org', 'plus', 'primary') : '') + table(['组织名称', '描述', '状态', '操作'], rows, '暂无组织');
  bindActions(); refreshIcons();
}

function showOrganization(id = '') {
  const organizations = state.organizations || [];
  const current = organizations.find(item => item.id === id) || {};
  const el = openModal(id ? '编辑组织' : '新增组织', `<form id="organization-form" class="space-y-4"><div><label class="label">组织名称 <span class="text-rose-600">*</span></label><input class="field" name="name" required value="${esc(current.name || '')}"></div><div><label class="label">上级组织</label><select class="field" name="parent_id"><option value="">根组织</option>${organizations.filter(item => item.id !== id).map(item => `<option value="${esc(item.id)}" ${current.parent_id === item.id ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}</select></div><div><label class="label">描述</label><textarea class="field" name="description">${esc(current.description || '')}</textarea></div><label class="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" name="enabled" ${current.enabled === false ? '' : 'checked'}> 启用组织</label><div class="modal-footer justify-between"><span>${id ? button('删除', `org-delete:${id}`, 'trash-2', 'danger') : ''}</span><span class="flex gap-2"><button type="button" class="btn-secondary" id="form-cancel">取消</button><button class="btn-primary" type="submit">${icon('save')}保存</button></span></div></form>`);
  $('#form-cancel', el).onclick = () => el.close();
  $('#organization-form', el).onsubmit = async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api(id ? `/api/organizations/${id}` : '/api/organizations', { method: id ? 'PATCH' : 'POST', body: JSON.stringify({ name: form.get('name'), parent_id: form.get('parent_id') || null, description: form.get('description') || null, enabled: form.has('enabled') }) });
      el.close(); setToast('组织已保存'); renderOrganizations();
    } catch (error) { setNotice(error.message); }
  };
  $('[data-action^="org-delete"]', el)?.addEventListener('click', async () => {
    if (await ask('删除组织', '仅无子组织的组织可以删除。')) { await api(`/api/organizations/${id}`, { method: 'DELETE' }); el.close(); setToast('组织已删除'); renderOrganizations(); }
  });
}

async function renderRoles() {
  const data = await api('/api/roles');
  const canConfigurePermissions = can('entity', 'roles', 'update') && can('entity', 'permissions', 'read') && can('entity', 'modules', 'read') && can('entity', 'resources', 'read');
  const rows = data.items.map(role => `<tr><td><div class="font-medium text-slate-800">${esc(role.name)}</div></td><td class="max-w-[280px] truncate text-slate-500">${esc(role.description || '-')}</td><td>${role.built_in ? badge('内置角色', 'blue') : status(role.enabled)}</td><td>${canConfigurePermissions ? `<button type="button" data-action="role-permissions:${role.id}" class="font-medium text-brand-600 hover:text-brand-700">配置权限</button>` : ''}</td><td><div class="flex justify-end">${can('entity', 'roles', 'delete') && !role.built_in ? button('删除', `role-delete:${role.id}`, 'trash-2') : ''}</div></td></tr>`).join('');
  $('#content').innerHTML = pageHeader('角色', can('entity', 'roles', 'create') ? button('新增角色', 'new-role', 'plus', 'primary') : '') + table(['角色', '描述', '状态', '权限', '操作'], rows, '暂无角色');
  bindActions(); refreshIcons();
}

function showNewRole() {
  const el = openModal('新增角色', `<form id="new-role-form" class="space-y-4"><div><label class="label">角色名称 <span class="text-rose-600">*</span></label><input class="field" name="name" required placeholder="例如内容审核员"></div><div><label class="label">描述</label><textarea class="field" name="description" placeholder="该角色可以承担的职责"></textarea></div><div class="modal-footer"><button type="button" id="form-cancel" class="btn-secondary">取消</button><button class="btn-primary" type="submit">${icon('plus')}创建角色</button></div></form>`);
  $('#form-cancel', el).onclick = () => el.close();
  $('#new-role-form', el).onsubmit = async event => {
    event.preventDefault();
    const buttonEl = $('button[type="submit"]', event.currentTarget);
    try {
      setLoading(buttonEl, true, '创建角色');
      await api('/api/roles', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
      el.close(); setToast('角色已创建'); renderRoles();
    } catch (error) { setNotice(error.message); } finally { setLoading(buttonEl, false, '创建角色'); }
  };
}

async function showRolePermissions(roleId) {
  const [permissions, assigned, modules, resources] = await Promise.all([api('/api/permissions'), api(`/api/roles/${roleId}/permissions`), api('/api/modules'), api('/api/resources')]);
  const assignedCodes = new Set(assigned.items.map(item => item.code));
  const groups = permissionGroups(permissions.items, modules.items, resources.items);
  const el = openModal('配置角色权限', `<form id="role-permissions-form" class="space-y-4"><div class="relative">${icon('search', 'pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400')}<input id="permission-filter" class="field pl-9" placeholder="筛选模块、资源或权限"></div>${selectionToolbar('permission_codes')}<div id="permission-options" class="selection-list selection-list-tall">${permissionOptions(groups, 'permission_codes', assignedCodes)}</div><div class="modal-footer"><button type="button" class="btn-secondary" id="form-cancel">取消</button><button class="btn-primary" type="submit">${icon('save')}保存权限</button></div></form>`, true);
  $('#form-cancel', el).onclick = () => el.close();
  $('#permission-filter', el).oninput = event => {
    filterPermissionOptions(el, event.target.value.toLowerCase());
  };
  bindSelectionToolbar(el, 'permission_codes');
  refreshIcons();
  $('#role-permissions-form', el).onsubmit = async event => {
    event.preventDefault();
    const selected = new Set(new FormData(event.currentTarget).getAll('permission_codes'));
    const buttonEl = $('button[type="submit"]', event.currentTarget);
    try {
      setLoading(buttonEl, true, '保存权限');
      await Promise.all(permissions.items.filter(permission => permission.enabled).map(permission => selected.has(permission.code) === assignedCodes.has(permission.code) ? null : api(`/api/roles/${roleId}/permissions/${encodeURIComponent(permission.code)}`, { method: selected.has(permission.code) ? 'POST' : 'DELETE' })));
      el.close(); setToast('角色权限已更新'); renderRoles();
    } catch (error) { setNotice(error.message); } finally { setLoading(buttonEl, false, '保存权限'); }
  };
}

async function renderPermissions() {
  const [permissions, modules, resources] = await Promise.all([
    api('/api/permissions'),
    can('entity', 'modules', 'read') ? api('/api/modules') : Promise.resolve(fallbackItems),
    can('entity', 'resources', 'read') ? api('/api/resources') : Promise.resolve(fallbackItems)
  ]);
  const scopeLabels = { global: '全部', owner: '本人归属', organization: '组织归属' };
  const groups = permissionGroups(permissions.items, modules.items, resources.items);
  const createPermission = can('entity', 'permissions', 'create') && can('entity', 'modules', 'read') && can('entity', 'resources', 'read') && can('entity', 'roles', 'read');
  $('#content').innerHTML = pageHeader('权限', createPermission ? button('新增权限', 'new-permission', 'plus', 'primary') : '')
    + `<div class="mb-3 flex items-center justify-between"><div class="relative w-full max-w-xs">${icon('search', 'pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400')}<input id="permission-list-filter" class="field pl-9" placeholder="筛选模块、资源或权限"></div><span class="ml-3 whitespace-nowrap text-xs text-slate-500">${permissionSections(groups).length} 类 · ${groups.length} 个资源 · ${permissions.items.length} 项权限</span></div>`
    + (groups.length ? panel(permissionDirectory(groups, scopeLabels), 'overflow-hidden') : panel(empty('暂无权限。先创建业务模块和资源，再配置可授权操作。')));
  $('#permission-list-filter').oninput = event => {
    filterPermissionDirectory($('#content'), event.target.value);
  };
  refreshIcons();
}

async function showPermission() {
  const [modules, resources, roles] = await Promise.all([api('/api/modules'), api('/api/resources'), api('/api/roles')]);
  const moduleOptions = modules.items.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
  const el = openModal('新增权限', `<form id="permission-form" class="space-y-5"><div class="grid gap-4 sm:grid-cols-2"><div><label class="label">权限名称 <span class="text-rose-600">*</span></label><input class="field" name="name" required placeholder="例如查看订单"></div><div><label class="label">业务模块 <span class="text-rose-600">*</span></label><select class="field" name="module_id" id="permission-module" required><option value="">请选择业务模块</option>${moduleOptions}</select></div></div><div><label class="label">资源 <span class="text-rose-600">*</span></label><select class="field" name="resource_id" id="permission-resource" required disabled><option value="">请先选择业务模块</option></select></div><div class="grid gap-4 sm:grid-cols-2"><div><label class="label">允许的操作 <span class="text-rose-600">*</span></label><select class="field" name="action" id="permission-action" required disabled><option value="">请先选择资源</option></select></div><div><label class="label">数据范围 <span class="text-rose-600">*</span></label><select class="field" name="scope" required><option value="global">全部资源</option><option value="owner">仅本人创建/拥有</option><option value="organization">所属组织</option></select><p class="field-help">实例归属由业务服务注册；超级管理员始终可操作。</p></div></div><div><label class="label">描述</label><textarea class="field" name="description" placeholder="说明这项操作允许做什么"></textarea></div><div><span class="label">同时授予角色</span>${selectionList(roles.items.filter(role => role.enabled), 'role_ids')}<p class="field-help">可留空，之后在角色页统一配置。</p></div><div class="modal-footer"><button type="button" class="btn-secondary" id="form-cancel">取消</button><button class="btn-primary" type="submit">${icon('plus')}创建权限</button></div></form>`);
  const updateResources = () => {
    const moduleId = $('#permission-module', el).value;
    const select = $('#permission-resource', el);
    const items = resources.items.filter(resource => resource.module_id === moduleId);
    select.disabled = !moduleId;
    select.innerHTML = `<option value="">${moduleId ? '请选择资源' : '请先选择业务模块'}</option>${items.map(item => `<option value="${esc(item.id)}">${esc(item.name)}（${esc(resourceLabel(item.resource_type))}）</option>`).join('')}`;
    const actionSelect = $('#permission-action', el);
    actionSelect.disabled = true;
    actionSelect.innerHTML = '<option value="">请先选择资源</option>';
  };
  const updateActions = () => {
    const resource = resources.items.find(item => item.id === $('#permission-resource', el).value);
    const select = $('#permission-action', el);
    const available = resource ? resourceActions[resource.resource_type] || actions : [];
    select.disabled = !resource;
    select.innerHTML = `<option value="">${resource ? '请选择操作' : '请先选择资源'}</option>${available.map(action => `<option value="${action}">${actionLabels[action]}</option>`).join('')}`;
  };
  $('#permission-module', el).onchange = updateResources;
  $('#permission-resource', el).onchange = updateActions;
  $('#form-cancel', el).onclick = () => el.close();
  $('#permission-form', el).onsubmit = async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const buttonEl = $('button[type="submit"]', event.currentTarget);
    try {
      setLoading(buttonEl, true, '创建权限');
      await api('/api/permissions', { method: 'POST', body: JSON.stringify({ name: form.get('name'), module_id: form.get('module_id'), resource_id: form.get('resource_id'), action: form.get('action'), scope: form.get('scope'), description: form.get('description') || undefined, role_ids: form.getAll('role_ids') }) });
      el.close(); setToast('权限已创建并绑定资源'); renderPermissions();
    } catch (error) { setNotice(error.message); } finally { setLoading(buttonEl, false, '创建权限'); }
  };
}

async function renderModules() {
  const [modules, resources, permissions] = await Promise.all([
    api('/api/modules'),
    can('entity', 'resources', 'read') ? api('/api/resources') : Promise.resolve(fallbackItems),
    can('entity', 'permissions', 'read') ? api('/api/permissions') : Promise.resolve(fallbackItems)
  ]);
  const resourceCount = resources.items.reduce((result, item) => ({ ...result, [item.module_id]: (result[item.module_id] || 0) + 1 }), {});
  const permissionCount = permissions.items.reduce((result, item) => ({ ...result, [item.module_id]: (result[item.module_id] || 0) + 1 }), {});
  const rows = modules.items.map(item => `<tr><td><div class="font-medium text-slate-800">${esc(item.name)}</div></td><td class="max-w-[380px] truncate text-slate-500">${esc(item.description || '-')}</td><td>${resourceCount[item.id] || 0}</td><td>${permissionCount[item.id] || 0}</td><td><div class="flex justify-end">${can('entity', 'modules', 'delete') && item.id !== 'authhub' ? button('删除', `module-delete:${item.id}`, 'trash-2') : ''}</div></td></tr>`).join('');
  $('#content').innerHTML = pageHeader('业务模块', state.me.is_super_admin ? button('新增业务模块', 'new-module', 'plus', 'primary') : '') + table(['业务模块', '描述', '资源', '权限', '操作'], rows, '暂无业务模块。先创建一个业务边界，再建立它的资源。');
  bindActions(); refreshIcons();
}

function showNewModule() {
  const el = openModal('新增业务模块', `<form id="module-form" class="space-y-5"><div><label class="label">模块名称 <span class="text-rose-600">*</span></label><input class="field" name="module_name" required placeholder="例如订单中心"></div><div><label class="label">描述</label><textarea class="field" name="description" placeholder="描述这个业务边界负责的能力"></textarea></div><div class="modal-footer"><button type="button" class="btn-secondary" id="form-cancel">取消</button><button class="btn-primary" type="submit">${icon('plus')}创建模块</button></div></form>`);
  $('#form-cancel', el).onclick = () => el.close();
  $('#module-form', el).onsubmit = async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const buttonEl = $('button[type="submit"]', event.currentTarget);
    try {
      setLoading(buttonEl, true, '创建模块');
      await api('/api/modules/register', { method: 'POST', body: JSON.stringify({ module_name: form.get('module_name'), description: form.get('description') || undefined, permissions: [], apis: [], resources: [], metadata: {} }) });
      el.close(); setToast('业务模块已创建'); renderModules();
    } catch (error) { setNotice(error.message); } finally { setLoading(buttonEl, false, '创建模块'); }
  };
}

async function renderResources() {
  const [resources, modules] = await Promise.all([api('/api/resources'), can('entity', 'modules', 'read') ? api('/api/modules') : Promise.resolve(fallbackItems)]);
  const moduleNames = Object.fromEntries(modules.items.map(item => [item.id, item.name]));
  const rows = resources.items.map(item => `<tr><td><div class="font-medium text-slate-800">${esc(item.name)}</div></td><td>${badge(resourceLabel(item.resource_type), 'blue')}</td><td class="max-w-[260px] truncate font-mono text-xs text-slate-600">${esc(item.resource_key)}</td><td class="text-slate-500">${esc(moduleNames[item.module_id] || '-')}</td><td><div class="flex justify-end">${can('entity', 'resources', 'delete') && !item.id.startsWith('authhub:') ? button('删除', `resource-delete:${item.id}`, 'trash-2') : ''}</div></td></tr>`).join('');
  $('#content').innerHTML = pageHeader('资源', can('entity', 'resources', 'create') && can('entity', 'modules', 'read') ? button('新增资源', 'new-resource', 'plus', 'primary') : '') + table(['资源', '资源类别', '资源标识', '业务模块', '操作'], rows, '暂无资源。资源是需要被授权的对象，必须属于一个业务模块。');
  bindActions(); refreshIcons();
}

async function renderResourceInstances() {
  const [instances, resources, users, organizations] = await Promise.all([
    api('/api/resource-instances'),
    can('entity', 'resources', 'read') ? api('/api/resources') : Promise.resolve(fallbackItems),
    can('entity', 'users', 'read') ? api('/api/users') : Promise.resolve(fallbackItems),
    can('entity', 'organizations', 'read') ? api('/api/organizations') : Promise.resolve(fallbackItems)
  ]);
  const resourceNames = Object.fromEntries(resources.items.map(item => [item.id, item.name]));
  const userNames = Object.fromEntries(users.items.map(item => [item.id, item.display_name || item.username]));
  const organizationNames = Object.fromEntries(organizations.items.map(item => [item.id, item.name]));
  const canManageGrants = can('entity', 'resource-instances', 'update') && can('entity', 'resources', 'read') && can('entity', 'users', 'read') && can('entity', 'permissions', 'read') && can('entity', 'modules', 'read') && can('entity', 'organizations', 'read');
  const rows = instances.items.map(item => `<tr><td><div class="font-medium text-slate-800">${esc(resourceNames[item.resource_id] || item.resource_id)}</div><div class="mt-0.5 max-w-[260px] truncate font-mono text-xs text-slate-500">${esc(item.resource_id)}</div></td><td class="font-mono text-xs text-slate-700">${esc(item.external_id)}</td><td class="text-slate-600">${esc(userNames[item.owner_user_id] || '-')}</td><td class="text-slate-600">${esc(organizationNames[item.organization_id] || '-')}</td><td>${item.grant_count ? badge(`${item.grant_count} 位协作者`, 'active') : '<span class="text-xs text-slate-400">未授权</span>'}</td><td><div class="flex justify-end">${canManageGrants ? button('协作授权', `instance-grants:${item.id}`, 'users-round', 'secondary') : ''}</div></td></tr>`).join('');
  $('#content').innerHTML = pageHeader('资源实例') + table(['资源', '业务记录 ID', '归属用户', '归属组织', '协作者', '操作'], rows, '暂无业务服务登记的资源实例。');
  bindActions(); refreshIcons();
}

async function showInstanceGrants(instanceId) {
  const [instances, grants, users, permissions, modules, resources, organizations] = await Promise.all([
    api('/api/resource-instances'), api(`/api/resource-instances/${encodeURIComponent(instanceId)}/grants`), api('/api/users'), api('/api/permissions'), api('/api/modules'), api('/api/resources'), api('/api/organizations')
  ]);
  const instance = instances.items.find(item => item.id === instanceId);
  if (!instance) throw new Error('资源实例不存在或已删除');
  const resource = resources.items.find(item => item.id === instance.resource_id);
  const userNames = Object.fromEntries(users.items.map(item => [item.id, item.display_name || item.username]));
  const organizationNames = Object.fromEntries(organizations.items.map(item => [item.id, item.name]));
  const availablePermissions = permissions.items.filter(item => item.enabled && item.resource_id === instance.resource_id);
  const groups = permissionGroups(availablePermissions, modules.items, resources.items);
  const collaborators = users.items.filter(item => item.enabled && !item.is_super_admin);
  const grantsByUser = new Map();
  grants.items.forEach(grant => {
    if (!grantsByUser.has(grant.user_id)) grantsByUser.set(grant.user_id, new Set());
    grantsByUser.get(grant.user_id).add(grant.permission_code);
  });
  let currentUserId = [...grantsByUser.keys()][0] || collaborators[0]?.id || '';
  const el = openModal('配置实例协作权限', `<form id="instance-grants-form" class="space-y-4"><div class="detail-strip"><div><span>资源</span><strong>${esc(resource?.name || instance.resource_id)}</strong></div><div><span>业务记录</span><strong class="font-mono">${esc(instance.external_id)}</strong></div><div><span>归属用户</span><strong>${esc(userNames[instance.owner_user_id] || '-')}</strong></div><div><span>归属组织</span><strong>${esc(organizationNames[instance.organization_id] || '-')}</strong></div></div><div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]"><div><label class="label">协作者</label><select id="instance-grant-user" class="field" ${collaborators.length ? '' : 'disabled'}>${collaborators.map(user => `<option value="${esc(user.id)}" ${currentUserId === user.id ? 'selected' : ''}>${esc(user.display_name || user.username)}（${esc(user.username)}）</option>`).join('')}</select></div><div class="self-end"><button type="button" id="instance-grant-clear" class="btn-secondary" ${currentUserId ? '' : 'disabled'}>${icon('user-minus')}移除授权</button></div></div><div class="flex items-center justify-between gap-3"><span class="label !mb-0">可操作权限</span>${selectionToolbar('grant_permission_codes')}</div><div id="instance-grant-options" class="selection-list selection-list-tall"></div><div id="instance-grant-summary" class="collaborator-summary"></div><div class="modal-footer"><button type="button" class="btn-secondary" id="form-cancel">取消</button><button class="btn-primary" type="submit" ${availablePermissions.length && collaborators.length ? '' : 'disabled'}>${icon('save')}保存协作权限</button></div></form>`, true);
  const renderSummary = () => {
    const items = [...grantsByUser.entries()].filter(([, codes]) => codes.size).map(([userId, codes]) => `<div><span>${icon('user-round', 'h-4 w-4')}${esc(userNames[userId] || userId)}</span><small>${esc([...codes].map(code => permissions.items.find(item => item.code === code)?.name || code).join('、'))}</small></div>`);
    $('#instance-grant-summary', el).innerHTML = items.length ? `<span class="label">已授权协作者</span>${items.join('')}` : '';
    refreshIcons();
  };
  const persistCurrentSelection = () => {
    if (!currentUserId) return;
    grantsByUser.set(currentUserId, new Set($$('input[name="grant_permission_codes"]:checked', el).map(input => input.value)));
    renderSummary();
  };
  const renderOptions = () => {
    const selected = grantsByUser.get(currentUserId) || new Set();
    $('#instance-grant-options', el).innerHTML = permissionOptions(groups, 'grant_permission_codes', selected);
    bindSelectionToolbar(el, 'grant_permission_codes', persistCurrentSelection);
    refreshIcons();
  };
  renderOptions(); renderSummary();
  $('#form-cancel', el).onclick = () => el.close();
  $('#instance-grant-user', el).onchange = event => { persistCurrentSelection(); currentUserId = event.target.value; renderOptions(); };
  $('#instance-grant-clear', el).onclick = () => { if (currentUserId) { grantsByUser.delete(currentUserId); renderOptions(); renderSummary(); } };
  $('#instance-grants-form', el).onsubmit = async event => {
    event.preventDefault(); persistCurrentSelection();
    const buttonEl = $('button[type="submit"]', event.currentTarget);
    const payload = [...grantsByUser.entries()].filter(([, codes]) => codes.size).map(([userId, codes]) => ({ user_id: userId, permission_codes: [...codes] }));
    try {
      setLoading(buttonEl, true, '保存协作权限');
      await api(`/api/resource-instances/${encodeURIComponent(instanceId)}/grants`, { method: 'PUT', body: JSON.stringify({ grants: payload }) });
      el.close(); setToast('实例协作权限已保存'); renderResourceInstances();
    } catch (error) { setNotice(error.message); } finally { setLoading(buttonEl, false, '保存协作权限'); }
  };
}

async function showNewResource() {
  const modules = await api('/api/modules');
  const moduleOptions = modules.items.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
  const el = openModal('新增资源', `<form id="resource-form" class="space-y-4"><div><label class="label">业务模块 <span class="text-rose-600">*</span></label><select class="field" name="module_id" required><option value="">请选择业务模块</option>${moduleOptions}</select></div><div><label class="label">资源类别 <span class="text-rose-600">*</span></label><select class="field" name="resource_type" id="resource-type" required>${Object.entries(resourceTypes).map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select></div><div><label class="label">资源名称 <span class="text-rose-600">*</span></label><input class="field" name="name" required placeholder="例如订单列表接口"></div><div><label class="label">资源标识 <span class="text-rose-600">*</span></label><input class="field font-mono" id="resource-key" name="resource_key" required placeholder="例如 /orders"><p id="resource-key-help" class="field-help">API 接口请填写稳定路径；其他资源填写上游用于识别对象的稳定键。</p></div><div class="modal-footer"><button type="button" class="btn-secondary" id="form-cancel">取消</button><button class="btn-primary" type="submit">${icon('plus')}创建资源</button></div></form>`);
  const updateHint = () => {
    const type = $('#resource-type', el).value;
    const key = $('#resource-key', el);
    const hints = {
      api: ['例如 /orders', 'API 接口请填写稳定路径；HTTP 方法可由上游路由或 SDK 附加。'],
      entity: ['例如 order', '填写业务实体或集合的稳定标识。'],
      mcp_server: ['例如 production-server', '填写 MCP Server 的稳定标识。'],
      mcp_tool: ['例如 search_orders', '填写 MCP Tool 的稳定名称。'],
      page: ['例如 orders-list', '填写页面或路由的稳定标识；菜单通常复用所属页面的查看权限。'],
      ui_action: ['例如 order-create', '填写按钮、批量命令或下拉操作的稳定标识。'],
      ui_component: ['例如 order-tabs', '填写 Tab、区域或其他显示组件的稳定标识。'],
      custom: ['例如 warehouse-zone', '填写上游系统用于识别该对象的稳定键。']
    };
    key.placeholder = hints[type][0]; $('#resource-key-help', el).textContent = hints[type][1];
  };
  $('#resource-type', el).onchange = updateHint;
  $('#form-cancel', el).onclick = () => el.close();
  $('#resource-form', el).onsubmit = async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const buttonEl = $('button[type="submit"]', event.currentTarget);
    try {
      setLoading(buttonEl, true, '创建资源');
      await api('/api/resources', { method: 'POST', body: JSON.stringify(Object.fromEntries(form)) });
      el.close(); setToast('资源已创建'); renderResources();
    } catch (error) { setNotice(error.message); } finally { setLoading(buttonEl, false, '创建资源'); }
  };
}

async function renderAudit() {
  const data = await api('/api/audit-events?limit=100');
  const rows = data.items.map(item => `<tr data-audit-row><td class="whitespace-nowrap text-xs text-slate-500">${esc(new Date(item.occurred_at).toLocaleString())}</td><td class="font-mono text-xs text-slate-700">${esc(item.action)}</td><td class="font-mono text-xs text-slate-500">${esc(item.actor_id || '-')}</td><td><span class="text-slate-600">${esc(item.target_type)}</span><span class="ml-1 font-mono text-xs text-slate-400">${esc(item.target_id || '')}</span></td><td>${badge(item.outcome, item.outcome === 'success' || item.outcome === 'allowed' ? 'active' : 'danger')}</td></tr>`).join('');
  $('#content').innerHTML = pageHeader('审计日志') + `<div class="mb-3 relative max-w-xs">${icon('search', 'pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400')}<input id="audit-filter" class="field pl-9" placeholder="筛选动作、对象或执行人"></div>` + table(['时间', '动作', '执行人', '目标', '结果'], rows, '暂无审计记录');
  $('#audit-filter').oninput = event => {
    const value = event.target.value.toLowerCase();
    $$('[data-audit-row]').forEach(row => row.classList.toggle('hidden', !row.textContent.toLowerCase().includes(value)));
  };
  refreshIcons();
}

async function performAction(action) {
  const [kind, ...parts] = action.split(':');
  if (kind === 'goto') return setPage(parts.join(':'));
  if (kind === 'new-user') return showNewUser();
  if (kind === 'new-org') return showOrganization();
  if (kind === 'new-role') return showNewRole();
  if (kind === 'new-permission') return showPermission();
  if (kind === 'new-module') return showNewModule();
  if (kind === 'new-resource') return showNewResource();
  if (kind === 'user-roles') return showUserRoles(parts[0]);
  if (kind === 'user-organizations') return showUserOrganizations(parts[0]);
  if (kind === 'role-permissions') return showRolePermissions(parts[0]);
  if (kind === 'instance-grants') return showInstanceGrants(parts[0]);
  if (kind === 'org-edit') return showOrganization(parts[0]);
  if (kind === 'user-toggle') {
    try { await api(`/api/users/${parts[0]}`, { method: 'PATCH', body: JSON.stringify({ enabled: parts[1] === 'true' }) }); setToast(parts[1] === 'true' ? '用户已启用' : '用户已停用'); renderUsers(); } catch (error) { setNotice(error.message); }
    return;
  }
  if (kind === 'role-delete') {
    if (await ask('删除角色', '删除后会解除该角色与用户、权限的关系。')) { try { await api(`/api/roles/${parts[0]}`, { method: 'DELETE' }); setToast('角色已删除'); renderRoles(); } catch (error) { setNotice(error.message); } }
    return;
  }
  if (kind === 'resource-delete') {
    if (await ask('删除资源', '已绑定权限的资源不能删除，请先处理对应权限。')) { try { await api(`/api/resources/${parts[0]}`, { method: 'DELETE' }); setToast('资源已删除'); renderResources(); } catch (error) { setNotice(error.message); } }
    return;
  }
  if (kind === 'module-delete') {
    if (await ask('删除业务模块', '删除后会移除该模块下的资源和权限。')) { try { await api(`/api/modules/${parts[0]}`, { method: 'DELETE' }); setToast('业务模块已删除'); renderModules(); } catch (error) { setNotice(error.message); } }
  }
}

function bindActions() { $$('[data-action]').forEach(element => { element.onclick = () => performAction(element.dataset.action); }); }

async function render() {
  clearNotice();
  $('#content').innerHTML = `<div class="grid gap-3"><div class="skeleton h-7 w-32"></div><div class="surface p-5"><div class="skeleton h-9 w-full"></div><div class="mt-3 skeleton h-9 w-full"></div><div class="mt-3 skeleton h-9 w-3/4"></div></div></div>`;
  try {
    await ({ overview: renderOverview, authorize: renderAuthorize, users: renderUsers, organizations: renderOrganizations, roles: renderRoles, permissions: renderPermissions, modules: renderModules, resources: renderResources, 'resource-instances': renderResourceInstances, audit: renderAudit }[state.page])();
  } catch (error) {
    $('#content').innerHTML = panel(`<div class="flex min-h-[240px] flex-col items-center justify-center p-6 text-center"><div class="mb-3 grid h-10 w-10 place-items-center rounded-full bg-rose-50 text-rose-600">${icon('circle-alert')}</div><p class="text-sm font-medium text-slate-700">无法加载此页面</p><p class="mt-1 text-sm text-slate-500">${esc(error.message)}</p><button type="button" id="retry" class="btn-secondary mt-4">${icon('refresh-cw')}重试</button></div>`);
    $('#retry').onclick = render; refreshIcons();
  }
}

async function initialize() {
  if (!state.token) return;
  try {
    state.me = await api('/api/auth/me');
    const snapshot = await api('/api/auth/user-permissions');
    state.permissions = new Set(snapshot.permissions || []);
    const page = allowedPage();
    if (!page) throw new Error('当前账户未被授予 AuthHub 管理权限');
    state.page = page;
    applyNavigationPermissions();
    $('#current-user').textContent = state.me.display_name || state.me.username;
    $('#login-view').classList.add('hidden'); $('#app-view').classList.remove('hidden');
    await render();
  } catch (error) {
    state.token = null; sessionStorage.removeItem('authhub.token'); $('#login-view').classList.remove('hidden');
    const alert = $('#login-error'); alert.classList.remove('hidden'); $('span', alert).textContent = error.message; refreshIcons();
  }
}

$('#login-form').onsubmit = async event => {
  event.preventDefault();
  const error = $('#login-error'); error.classList.add('hidden');
  const buttonEl = $('#login-submit');
  try {
    setLoading(buttonEl, true, '登录');
    const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
    state.token = data.access_token; sessionStorage.setItem('authhub.token', state.token); await initialize();
  } catch (reason) { error.classList.remove('hidden'); $('span', error).textContent = reason.message; refreshIcons(); } finally { setLoading(buttonEl, false, '登录'); }
};
$('#toggle-password').onclick = () => {
  const field = $('#password'); field.type = field.type === 'password' ? 'text' : 'password';
  $('#toggle-password').title = field.type === 'password' ? '显示密码' : '隐藏密码';
  $('#toggle-password').innerHTML = icon(field.type === 'password' ? 'eye' : 'eye-off'); refreshIcons();
};
$('#logout-button').onclick = async () => { try { await api('/api/auth/logout', { method: 'POST' }); } finally { state.token = null; sessionStorage.removeItem('authhub.token'); location.reload(); } };
$('#menu-button').onclick = () => { $('#sidebar').classList.add('open'); $('#sidebar-backdrop').classList.remove('hidden'); };
$('#sidebar-backdrop').onclick = () => { $('#sidebar').classList.remove('open'); $('#sidebar-backdrop').classList.add('hidden'); };
$$('.nav-item').forEach(item => { item.onclick = () => setPage(item.dataset.page); });
loadRuntimeVersion();
initialize();
refreshIcons();
