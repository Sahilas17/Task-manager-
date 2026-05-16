Team Task Manager - Full-Stack Assessment

Overview
Team Task Manager is a full-stack project and task tracking app built for the Ethara AI internal assessment. Users can sign up, log in, create projects, add team members, assign tasks, update task status, and monitor progress from a dashboard.

Tech Stack
- Backend: Python 3 standard library HTTP server
- Database: SQLite SQL database
- Frontend: HTML, CSS, vanilla JavaScript
- Auth: PBKDF2 password hashing and signed bearer tokens
- Deployment target: Railway

Features
- Signup and login
- First registered user automatically becomes a global Admin
- Project creation and project-level team roles
- Role-based access control:
  - Global Admin can access all projects
  - Project Admin can manage members and tasks in that project
  - Member can view assigned projects and update their assigned task status
- Task creation with assignee, status, priority, and due date
- Dashboard with project count, task count, personal task count, completed tasks, status breakdown, recent tasks, and overdue tasks
- REST API with validation and SQL relationships

Local Setup
1. Install Python 3.12 or newer.
2. Open a terminal in the project folder.
3. Run:
   python app.py
4. Open:
   http://127.0.0.1:8000

Railway Deployment
1. Push this folder to a GitHub repository.
2. Open Railway and create a new project from the GitHub repo.
3. Railway will use the Procfile:
   web: python app.py
4. Add an environment variable in Railway:
   SESSION_SECRET=use-a-long-random-secret
5. Railway provides PORT automatically.
6. After deployment, open the Railway generated domain.

Optional Railway Persistence Note
The app uses SQLite at data/task_manager.sqlite3 by default. For longer-lived production data on Railway, attach a Railway Volume and set:
DB_PATH=/data/task_manager.sqlite3

Important Usage Notes
- The first account you create is the global Admin account.
- Create additional accounts from Signup, then add them to projects from the project team form.
- Members can update only the status of tasks assigned to them.

Submission
Live Application URL:
Add your Railway URL here after deployment.

GitHub Repository Link:
Add your GitHub repository URL here after pushing the project.

API Summary
- POST /api/auth/signup
- POST /api/auth/login
- GET /api/auth/me
- GET /api/users
- GET /api/dashboard
- GET /api/projects
- POST /api/projects
- GET /api/projects/:id
- PUT /api/projects/:id
- DELETE /api/projects/:id
- POST /api/projects/:id/members
- DELETE /api/projects/:id/members/:userId
- POST /api/projects/:id/tasks
- PUT /api/tasks/:id
- DELETE /api/tasks/:id
