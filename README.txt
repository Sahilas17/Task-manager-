# Team Task Manager – Full-Stack Assessment

## Overview

Team Task Manager is a full-stack project and task management application developed for the Ethara AI technical assessment. The platform enables teams to manage projects, assign tasks, track progress, and collaborate efficiently through a secure role-based access system.

The application includes authentication, project management, task tracking, dashboard analytics, and RESTful APIs integrated with a relational database.

---

# Tech Stack

### Backend

* Python 3
* RESTful API architecture

### Frontend

* HTML5
* CSS3
* Vanilla JavaScript

### Database

* SQLite

### Authentication & Security

* PBKDF2 password hashing
* Signed bearer token authentication

### Deployment

* Railway

---

# Key Features

* User Signup and Login
* Secure token-based authentication
* Role-based access control (Global Admin, Project Admin, Member)
* Project creation and team management
* Task creation, assignment, status updates, and priority tracking
* Dashboard with task statistics, recent activity, and overdue tasks
* REST APIs with proper validation and SQL relationships
* Responsive and lightweight interface

---

# Role-Based Access Control

* The first registered user automatically becomes the Global Admin.
* Global Admins can manage all projects and users.
* Project Admins can manage project members and tasks.
* Members can view assigned projects and update the status of their own tasks.

---

# Dashboard Features

The dashboard provides:

* Total projects and tasks
* Completed and pending task counts
* Personal assigned tasks
* Status-based analytics
* Recent tasks and overdue task monitoring

---

# API Endpoints

### Authentication

* `POST /api/auth/signup`
* `POST /api/auth/login`
* `GET /api/auth/me`

### Projects

* `GET /api/projects`
* `POST /api/projects`
* `PUT /api/projects/:id`
* `DELETE /api/projects/:id`

### Tasks

* `POST /api/projects/:id/tasks`
* `PUT /api/tasks/:id`
* `DELETE /api/tasks/:id`

### Dashboard & Users

* `GET /api/dashboard`
* `GET /api/users`

---

# Local Development

Run the application locally using Python 3.12 or later:

```bash id="ov1qzt"
python app.py
```

Application URL:

```text id="pw8rvy"
http://127.0.0.1:8000
```

---

# Deployment

The application is configured for deployment on Railway with environment variable support and optional persistent SQLite storage using Railway Volumes.

---

# Submission

### Live Application URL

Add Railway deployment URL here.

### GitHub Repository

Add GitHub repository URL here.

---

# Conclusion

Team Task Manager demonstrates full-stack development concepts including secure authentication, role-based authorization, REST API development, relational database management, task workflow automation, and cloud deployment in a scalable and production-oriented architecture.
