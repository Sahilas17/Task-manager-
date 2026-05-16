const state = {
  token: localStorage.getItem("tm_token"),
  user: null,
  users: [],
  projects: [],
  selectedProject: null,
  activeView: "dashboard",
  authMode: "login",
};

const statusLabels = {
  todo: "To do",
  in_progress: "In progress",
  review: "Review",
  done: "Done",
};

const statusOrder = ["todo", "in_progress", "review", "done"];

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(date) {
  if (!date) return "No due date";
  return new Date(`${date}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function isOverdue(task) {
  const today = new Date().toISOString().slice(0, 10);
  return task.dueDate && task.dueDate < today && task.status !== "done";
}

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), 3200);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Request failed.");
  }
  return data;
}

function setAuthMode(mode) {
  state.authMode = mode;
  $("#loginTab").classList.toggle("active", mode === "login");
  $("#signupTab").classList.toggle("active", mode === "signup");
  $("#nameField").classList.toggle("hidden", mode === "login");
  $("#authSubmit").textContent = mode === "login" ? "Login" : "Create Account";
  $("#passwordInput").autocomplete = mode === "login" ? "current-password" : "new-password";
}

function setView(view) {
  state.activeView = view;
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((panel) => panel.classList.add("hidden"));
  $(`#${view}View`).classList.remove("hidden");
  $("#pageTitle").textContent = view === "dashboard" ? "Dashboard" : view === "projects" ? "Projects" : "Team";
  if (view === "dashboard") loadDashboard();
  if (view === "team") renderTeam();
}

function renderShell() {
  $("#authView").classList.toggle("hidden", Boolean(state.user));
  $("#appView").classList.toggle("hidden", !state.user);
  if (!state.user) return;
  $("#currentUser").innerHTML = `<span>${escapeHtml(state.user.name)}</span><span class="pill">${state.user.role}</span>`;
  $("#userRole").textContent = state.user.role === "admin" ? "Global Admin" : "Member";
}

async function loginOrSignup(event) {
  event.preventDefault();
  const payload = {
    email: $("#emailInput").value.trim(),
    password: $("#passwordInput").value,
  };
  if (state.authMode === "signup") payload.name = $("#nameInput").value.trim();
  try {
    const data = await api(`/api/auth/${state.authMode}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.token = data.token;
    state.user = data.user;
    localStorage.setItem("tm_token", state.token);
    $("#authForm").reset();
    renderShell();
    await bootstrapData();
    setView("dashboard");
    toast(`Welcome, ${state.user.name}.`);
  } catch (error) {
    toast(error.message);
  }
}

function logout() {
  localStorage.removeItem("tm_token");
  state.token = null;
  state.user = null;
  state.users = [];
  state.projects = [];
  state.selectedProject = null;
  renderShell();
}

async function bootstrapData() {
  const [usersData, projectsData] = await Promise.all([api("/api/users"), api("/api/projects")]);
  state.users = usersData.users;
  state.projects = projectsData.projects;
  renderProjectsList();
  renderTeam();
}

async function loadDashboard() {
  try {
    const data = await api("/api/dashboard");
    renderDashboard(data);
  } catch (error) {
    toast(error.message);
  }
}

function renderDashboard(data) {
  const metrics = [
    ["Projects", data.summary.projects],
    ["Tasks", data.summary.tasks],
    ["My tasks", data.summary.myTasks],
    ["Overdue", data.summary.overdue],
    ["Completed", data.summary.completed],
  ];
  const maxStatus = Math.max(1, ...Object.values(data.statusCounts));
  $("#dashboardView").innerHTML = `
    <div class="metrics">
      ${metrics.map(([label, value]) => `<article class="metric"><span>${label}</span><strong>${value}</strong></article>`).join("")}
    </div>
    <div class="dashboard-grid">
      <section class="panel">
        <div class="panel-head"><h3>Status Overview</h3></div>
        <div class="status-bars">
          ${statusOrder
            .map(
              (status) => `
              <div class="status-row">
                <span>${statusLabels[status]}</span>
                <div class="bar"><span style="width:${(data.statusCounts[status] / maxStatus) * 100}%"></span></div>
                <strong>${data.statusCounts[status]}</strong>
              </div>`
            )
            .join("")}
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h3>Recent Tasks</h3></div>
        <div class="task-list">${renderTaskList(data.recentTasks)}</div>
      </section>
      <section class="panel">
        <div class="panel-head"><h3>Overdue Tasks</h3></div>
        <div class="task-list">${renderTaskList(data.overdueTasks)}</div>
      </section>
      <section class="panel">
        <div class="panel-head"><h3>Project Progress</h3></div>
        <div class="task-list">
          ${state.projects.length ? state.projects.map(renderProjectProgress).join("") : `<div class="empty-state">No projects yet.</div>`}
        </div>
      </section>
    </div>
  `;
}

function renderProjectProgress(project) {
  return `
    <article class="task-item">
      <header><h4>${escapeHtml(project.name)}</h4><span class="pill">${project.progress}%</span></header>
      <div class="progress-track"><span style="width:${project.progress}%"></span></div>
      <small class="muted">${project.taskDone} of ${project.taskTotal} tasks done</small>
    </article>
  `;
}

function renderTaskList(tasks) {
  if (!tasks || !tasks.length) return `<div class="empty-state">Nothing to show.</div>`;
  return tasks
    .map(
      (task) => `
      <article class="task-item">
        <header>
          <h4>${escapeHtml(task.title)}</h4>
          <span class="pill ${task.priority}">${task.priority}</span>
        </header>
        <div class="meta">
          <span class="pill">${statusLabels[task.status]}</span>
          <span class="pill">${escapeHtml(task.assignee?.name || "Unassigned")}</span>
          <span class="pill ${isOverdue(task) ? "overdue" : ""}">${formatDate(task.dueDate)}</span>
        </div>
      </article>
    `
    )
    .join("");
}

function renderProjectsList() {
  const list = $("#projectsList");
  if (!state.projects.length) {
    list.innerHTML = `<div class="empty-state">No projects yet.</div>`;
    return;
  }
  list.innerHTML = state.projects
    .map(
      (project) => `
      <button class="project-row ${state.selectedProject?.id === project.id ? "active" : ""}" data-project-id="${project.id}" type="button">
        <div>
          <h4>${escapeHtml(project.name)}</h4>
          <small class="muted">${project.members.length} members · ${project.taskTotal} tasks</small>
        </div>
        <span class="pill">${project.progress}%</span>
      </button>
    `
    )
    .join("");
}

async function createProject(event) {
  event.preventDefault();
  try {
    const data = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        name: $("#projectName").value.trim(),
        description: $("#projectDescription").value.trim(),
      }),
    });
    $("#projectForm").reset();
    await bootstrapData();
    await selectProject(data.project.id);
    toast("Project created.");
  } catch (error) {
    toast(error.message);
  }
}

async function selectProject(projectId) {
  try {
    const data = await api(`/api/projects/${projectId}`);
    state.selectedProject = data.project;
    renderProjectsList();
    renderProjectDetail();
  } catch (error) {
    toast(error.message);
  }
}

function canManageSelectedProject() {
  return state.selectedProject?.currentUserRole === "admin";
}

function renderProjectDetail() {
  const project = state.selectedProject;
  if (!project) {
    $("#projectDetail").className = "project-detail empty-state";
    $("#projectDetail").textContent = "Select or create a project.";
    return;
  }
  $("#projectDetail").className = "project-detail";
  const canManage = canManageSelectedProject();
  $("#projectDetail").innerHTML = `
    <div class="project-hero">
      <div class="panel-head">
        <div>
          <h3>${escapeHtml(project.name)}</h3>
          <p class="muted">${escapeHtml(project.description || "No description")}</p>
        </div>
        <span class="pill">${project.currentUserRole}</span>
      </div>
      <div class="progress-track"><span style="width:${project.progress}%"></span></div>
      <small class="muted">${project.taskDone} of ${project.taskTotal} tasks done</small>
    </div>

    ${
      canManage
        ? `
      <section class="panel">
        <div class="panel-head"><h3>Add Task</h3></div>
        <form id="taskForm" class="form-grid">
          <label class="wide"><span>Title</span><input id="taskTitle" minlength="3" required /></label>
          <label class="wide"><span>Description</span><textarea id="taskDescription" rows="3"></textarea></label>
          <label><span>Assignee</span><select id="taskAssignee"><option value="">Unassigned</option>${memberOptions(project)}</select></label>
          <label><span>Status</span><select id="taskStatus">${statusOptions("todo")}</select></label>
          <label><span>Priority</span><select id="taskPriority">${priorityOptions("medium")}</select></label>
          <label><span>Due date</span><input id="taskDueDate" type="date" /></label>
          <button class="primary wide" type="submit">Create Task</button>
        </form>
      </section>

      <section class="panel">
        <div class="panel-head"><h3>Add Team Member</h3></div>
        <form id="memberForm" class="form-grid">
          <label><span>User</span><select id="memberUser">${availableUserOptions(project)}</select></label>
          <label><span>Role</span><select id="memberRole"><option value="member">Member</option><option value="admin">Admin</option></select></label>
          <button class="primary wide" type="submit">Add Member</button>
        </form>
      </section>
    `
        : ""
    }

    <section class="panel">
      <div class="panel-head"><h3>Team</h3></div>
      <div class="member-list">${project.members.map((member) => renderProjectMember(member, canManage)).join("")}</div>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>Tasks</h3></div>
      <div class="task-board">
        ${statusOrder.map((status) => renderTaskColumn(status, project.tasks.filter((task) => task.status === status), canManage)).join("")}
      </div>
    </section>
  `;
  if (canManage) {
    $("#taskForm").addEventListener("submit", createTask);
    $("#memberForm").addEventListener("submit", addMember);
  }
}

function memberOptions(project) {
  return project.members.map((member) => `<option value="${member.id}">${escapeHtml(member.name)}</option>`).join("");
}

function availableUserOptions(project) {
  const memberIds = new Set(project.members.map((member) => member.id));
  const options = state.users
    .filter((user) => !memberIds.has(user.id))
    .map((user) => `<option value="${user.id}">${escapeHtml(user.name)} (${escapeHtml(user.email)})</option>`)
    .join("");
  return options || `<option value="">All users are already members</option>`;
}

function statusOptions(selected) {
  return statusOrder.map((status) => `<option value="${status}" ${selected === status ? "selected" : ""}>${statusLabels[status]}</option>`).join("");
}

function priorityOptions(selected) {
  return ["low", "medium", "high"].map((priority) => `<option value="${priority}" ${selected === priority ? "selected" : ""}>${priority}</option>`).join("");
}

function renderProjectMember(member, canManage) {
  const canRemove = canManage && member.id !== state.user.id;
  return `
    <article class="member-row">
      <div>
        <strong>${escapeHtml(member.name)}</strong>
        <div class="muted">${escapeHtml(member.email)}</div>
      </div>
      <div class="project-actions">
        <span class="pill">${member.projectRole}</span>
        ${canRemove ? `<button class="ghost" data-remove-member="${member.id}" type="button">Remove</button>` : ""}
      </div>
    </article>
  `;
}

function renderTaskColumn(status, tasks, canManage) {
  return `
    <div class="task-column">
      <h4>${statusLabels[status]}</h4>
      ${tasks.length ? tasks.map((task) => renderProjectTask(task, canManage)).join("") : `<small class="muted">No tasks</small>`}
    </div>
  `;
}

function renderProjectTask(task, canManage) {
  const canUpdateStatus = canManage || task.assigneeId === state.user.id;
  return `
    <article class="task-item">
      <header>
        <h4>${escapeHtml(task.title)}</h4>
        <span class="pill ${task.priority}">${task.priority}</span>
      </header>
      ${task.description ? `<p class="muted">${escapeHtml(task.description)}</p>` : ""}
      <div class="meta">
        <span class="pill">${escapeHtml(task.assignee?.name || "Unassigned")}</span>
        <span class="pill ${isOverdue(task) ? "overdue" : ""}">${formatDate(task.dueDate)}</span>
      </div>
      <div class="task-actions">
        ${
          canUpdateStatus
            ? `<select data-task-status="${task.id}" aria-label="Task status">${statusOptions(task.status)}</select>`
            : `<span class="pill">${statusLabels[task.status]}</span>`
        }
        ${canManage ? `<button class="danger" data-delete-task="${task.id}" type="button">Delete</button>` : ""}
      </div>
    </article>
  `;
}

async function addMember(event) {
  event.preventDefault();
  if (!$("#memberUser").value) {
    toast("Choose a user to add.");
    return;
  }
  try {
    const data = await api(`/api/projects/${state.selectedProject.id}/members`, {
      method: "POST",
      body: JSON.stringify({
        userId: $("#memberUser").value,
        role: $("#memberRole").value,
      }),
    });
    state.selectedProject = data.project;
    await bootstrapData();
    state.selectedProject = data.project;
    renderProjectDetail();
    toast("Member added.");
  } catch (error) {
    toast(error.message);
  }
}

async function createTask(event) {
  event.preventDefault();
  try {
    const data = await api(`/api/projects/${state.selectedProject.id}/tasks`, {
      method: "POST",
      body: JSON.stringify({
        title: $("#taskTitle").value.trim(),
        description: $("#taskDescription").value.trim(),
        assigneeId: $("#taskAssignee").value,
        status: $("#taskStatus").value,
        priority: $("#taskPriority").value,
        dueDate: $("#taskDueDate").value || null,
      }),
    });
    state.selectedProject = data.project;
    await bootstrapData();
    state.selectedProject = data.project;
    renderProjectDetail();
    toast("Task created.");
  } catch (error) {
    toast(error.message);
  }
}

async function updateTaskStatus(taskId, status) {
  try {
    const data = await api(`/api/tasks/${taskId}`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    });
    state.selectedProject = data.project;
    await bootstrapData();
    state.selectedProject = data.project;
    renderProjectDetail();
    if (state.activeView === "dashboard") loadDashboard();
  } catch (error) {
    toast(error.message);
  }
}

async function deleteTask(taskId) {
  try {
    const data = await api(`/api/tasks/${taskId}`, { method: "DELETE" });
    state.selectedProject = data.project;
    await bootstrapData();
    state.selectedProject = data.project;
    renderProjectDetail();
    toast("Task deleted.");
  } catch (error) {
    toast(error.message);
  }
}

async function removeMember(userId) {
  try {
    const data = await api(`/api/projects/${state.selectedProject.id}/members/${userId}`, { method: "DELETE" });
    state.selectedProject = data.project;
    await bootstrapData();
    state.selectedProject = data.project;
    renderProjectDetail();
    toast("Member removed.");
  } catch (error) {
    toast(error.message);
  }
}

function renderTeam() {
  const usersById = new Map(state.users.map((user) => [user.id, { ...user, projectCount: 0, taskCount: 0 }]));
  state.projects.forEach((project) => {
    project.members.forEach((member) => {
      const row = usersById.get(member.id);
      if (row) row.projectCount += 1;
    });
  });
  $("#teamView").innerHTML = `
    <section class="panel">
      <div class="panel-head"><h3>Users</h3><span class="pill">${state.users.length} total</span></div>
      <div class="member-list">
        ${Array.from(usersById.values())
          .map(
            (user) => `
            <article class="member-row">
              <div>
                <strong>${escapeHtml(user.name)}</strong>
                <div class="muted">${escapeHtml(user.email)}</div>
              </div>
              <div class="project-actions">
                <span class="pill">${user.role}</span>
                <span class="pill">${user.projectCount} projects</span>
              </div>
            </article>
          `
          )
          .join("")}
      </div>
    </section>
  `;
}

document.addEventListener("click", (event) => {
  const projectButton = event.target.closest("[data-project-id]");
  if (projectButton) selectProject(projectButton.dataset.projectId);

  const removeButton = event.target.closest("[data-remove-member]");
  if (removeButton) removeMember(removeButton.dataset.removeMember);

  const deleteButton = event.target.closest("[data-delete-task]");
  if (deleteButton) deleteTask(deleteButton.dataset.deleteTask);
});

document.addEventListener("change", (event) => {
  const statusSelect = event.target.closest("[data-task-status]");
  if (statusSelect) updateTaskStatus(statusSelect.dataset.taskStatus, statusSelect.value);
});

document.querySelectorAll(".nav-button").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

$("#loginTab").addEventListener("click", () => setAuthMode("login"));
$("#signupTab").addEventListener("click", () => setAuthMode("signup"));
$("#authForm").addEventListener("submit", loginOrSignup);
$("#logoutButton").addEventListener("click", logout);
$("#projectForm").addEventListener("submit", createProject);

async function init() {
  setAuthMode("login");
  if (!state.token) {
    renderShell();
    return;
  }
  try {
    const data = await api("/api/auth/me");
    state.user = data.user;
    renderShell();
    await bootstrapData();
    setView("dashboard");
  } catch {
    logout();
  }
}

init();
