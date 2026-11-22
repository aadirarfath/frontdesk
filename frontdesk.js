'use strict';

const byId = id => document.getElementById(id);
const entry = byId('entry');
const workspace = byId('workspace');
const detail = byId('detail');
const feedback = byId('feedback');
const create = byId('create');
const filter = byId('filter');
let key = '';
let user;
let selected;
let selectionVersion = 0;
let queueVersion = 0;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function api(path, payload) {
  const headers = { Authorization: 'Bearer ' + key };
  const options = { headers };
  if (payload !== undefined) {
    options.method = 'POST';
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(payload);
  }
  const response = await fetch('/api' + path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'The request failed. Try again.');
  return data;
}

function report(error) {
  feedback.textContent = error.message;
  feedback.hidden = false;
}

function control(button, operation) {
  button.disabled = true;
  feedback.hidden = true;
  Promise.resolve().then(operation).catch(report).finally(() => {
    button.disabled = false;
  });
}

function formatTime(value) {
  return new Intl.DateTimeFormat('en-IN', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata',
  }).format(new Date(value)) + ' IST';
}

function badges(ticket) {
  const tags = element('div', undefined, 'tags');
  tags.append(element('span', ticket.priority, 'tag ' + ticket.priority));
  tags.append(element('span', ticket.status, 'tag ' + ticket.status));
  if (ticket.reply_late || ticket.resolution_late) {
    tags.append(element('span', 'Overdue', 'tag overdue'));
  }
  return tags;
}

function visible(ticket) {
  switch (filter.value) {
    case 'mine': return ticket.owner === user.id;
    case 'unclaimed': return !ticket.owner && ['open', 'waiting'].includes(ticket.status);
    case 'late': return ticket.reply_late || ticket.resolution_late;
    case 'waiting': return ticket.status === 'waiting';
    default: return true;
  }
}

async function loadQueue() {
  const version = ++queueVersion;
  const rows = await api('/tickets');
  if (version !== queueVersion) return;
  const list = byId('tickets');
  list.replaceChildren();
  for (const ticket of rows.filter(visible)) {
    const row = element('button', undefined, 'ticket');
    row.setAttribute('aria-current', String(selected === ticket.id));
    row.append(element('strong', '#' + ticket.id + ' · ' + ticket.subject), badges(ticket));
    if (user.role === 'agent') row.append(element('span', ticket.owner || 'Unclaimed', 'meta'));
    row.addEventListener('click', () => control(row, () => openTicket(ticket.id)));
    list.append(row);
  }
  if (!list.children.length) list.append(element('p', 'No tickets in this view.'));
}

function button(label, task, className) {
  const node = element('button', label, className);
  node.type = 'button';
  node.addEventListener('click', () => control(node, task));
  return node;
}

async function action(id, name, payload = {}) {
  try {
    await api('/tickets/' + id + '/' + name, payload);
  } catch (error) {
    if (name === 'claim' && selected === id) await openTicket(id);
    throw error;
  }
  if (selected === id) await openTicket(id);
}

function compose(id, name, caption, label) {
  const form = element('form');
  const field = element('label', caption);
  const input = element('textarea');
  input.required = true;
  input.maxLength = 5000;
  field.append(input);
  const submit = element('button', label, name === 'note' ? undefined : 'primary');
  form.append(field, submit);
  if (name === 'reply' && user.role === 'agent') {
    const ask = element('button', 'Send and wait for customer');
    ask.value = 'ask';
    form.append(' ', ask);
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    control(event.submitter || submit, () => action(id, event.submitter?.value || name, { body: input.value }));
  });
  return form;
}

function controls(ticket) {
  const id = ticket.id;
  const active = ['open', 'waiting'].includes(ticket.status);
  if (user.role === 'customer') {
    if (active) detail.append(compose(id, 'reply', 'Message to support', 'Send message'));
    if (ticket.status === 'resolved') detail.append(compose(id, 'reopen', 'Why should this ticket reopen?', 'Reopen ticket'));
    return;
  }
  const actions = element('div', undefined, 'actions');
  if (active && !ticket.owner) actions.append(button('Claim ticket', () => action(id, 'claim')));
  if (active && ticket.owner === user.id) {
    actions.append(button('Mark resolved', () => action(id, 'resolve')));
    const label = element('label', 'Priority');
    const priority = element('select');
    for (const value of ['urgent', 'medium', 'low']) priority.add(new Option(value, value));
    priority.value = ticket.priority;
    label.append(priority);
    actions.append(label, button('Update priority', () => action(id, 'priority', { priority: priority.value })));
    detail.append(compose(id, 'reply', 'Public reply to customer', 'Send reply'));
  }
  detail.append(actions, compose(id, 'note', 'Private note for the support team', 'Save private note'));
}

async function openTicket(id) {
  selected = id;
  const version = ++selectionVersion;
  const { ticket, history } = await api('/tickets/' + id);
  if (version !== selectionVersion) return;
  detail.replaceChildren(element('h2', '#' + id + ' · ' + ticket.subject), badges(ticket));
  if (user.role === 'agent') {
    const timing = element('div', undefined, 'meta');
    timing.append(
      element('p', 'Assigned to ' + (ticket.owner || 'no agent') + ' · Customer ' + ticket.customer),
      element('p', 'First reply due ' + formatTime(ticket.reply_due)),
      element('p', ticket.status === 'waiting'
        ? 'Resolution clock paused · Auto-close ' + formatTime(ticket.close_due_at)
        : 'Resolution due ' + formatTime(ticket.resolution_due)),
    );
    detail.append(timing);
  }
  const timeline = element('ol', undefined, 'timeline');
  for (const item of history) {
    const line = element('li', undefined, item.kind === 'internal_note' ? 'private' : '');
    const title = item.kind.replaceAll('_', ' ');
    line.append(element('strong', title[0].toUpperCase() + title.slice(1)));
    line.append(element('div', (item.actor ? item.actor + ' · ' : '') + formatTime(item.at), 'meta'));
    if (item.body) line.append(element('p', item.body));
    timeline.append(line);
  }
  detail.append(timeline);
  controls(ticket);
  await loadQueue();
}

byId('login').addEventListener('submit', event => {
  event.preventDefault();
  control(event.submitter, async () => {
    key = byId('key').value;
    user = await api('/me');
    byId('key').value = '';
    filter.value = 'all';
    create.hidden = user.role !== 'customer';
    byId('filter-label').hidden = user.role !== 'agent';
    byId('heading').textContent = user.role === 'agent' ? 'Support inbox' : 'My tickets';
    byId('identity').textContent = 'Signed in as ' + user.id;
    entry.hidden = true;
    workspace.hidden = false;
    byId('logout').hidden = false;
    await loadQueue();
  });
});
create.addEventListener('submit', event => {
  event.preventDefault();
  control(event.submitter, async () => {
    const ticket = await api('/tickets', Object.fromEntries(new FormData(create)));
    create.reset();
    await openTicket(ticket.id);
  });
});
filter.addEventListener('change', () => loadQueue().catch(report));
byId('refresh').addEventListener('click', event => control(event.currentTarget, () => selected ? openTicket(selected) : loadQueue()));
byId('logout').addEventListener('click', () => location.reload());

