# Faida App - Stock & Sales Management System

A Flask-based inventory and sales management application designed Telecom vender and distributers businesses in the DRC (Bukavu, Goma, Lubumbashi).

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional)
- Git

### Local Development Setup

```bash
# Clone the repository
git clone https://github.com/your-username/airtfast.git
cd airtfast

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
cd src
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your settings

# Initialize database
flask db upgrade

# Create superadmin (first time only)
flask setup create-superadmin

# Initialize stock (optional, for demo data)
flask setup init-stock

# Run the application
flask run
```

### Docker Setup

```bash
# Build and run with Docker Compose
docker-compose up --build

# Run setup commands
docker-compose run --rm airtfast_setup

# Stop containers
docker-compose down
```

---

## 🗄️ Database Configuration

### Option 1: Local SQLite (Development)

Default configuration uses SQLite. No additional setup needed.

### Option 2: Neon PostgreSQL (Recommended for Production)

1. Create account at [console.neon.tech](https://console.neon.tech)
2. Create a new project
3. Get your connection string
4. Set in `.env`:

```bash
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require
```

### Option 3: Render PostgreSQL

If using Render's managed PostgreSQL, the connection string is automatically provided.

---

## 🔐 Environment Variables

Create a `.env` file in the `src` directory:

```bash
# Flask
FLASK_APP=run.py
FLASK_ENV=development  # or 'production'
SECRET_KEY=your-secret-key-here

# Database
DATABASE_URL=sqlite:///db.sqlite3  # or PostgreSQL connection string

# Optional
LOG_LEVEL=INFO
```

---

## 📁 Project Structure

```
src/
├── apps/
│   ├── auth/           # Authentication module
│   │   ├── routes.py   # Login, register, logout
│   │   ├── forms.py    # WTForms
│   │   └── utils.py    # Auth utilities
│   ├── main/           # Main application module
│   │   ├── routes.py   # Dashboard, sales, stock
│   │   ├── forms.py    # Business forms
│   │   └── utils.py    # Business logic
│   ├── errors/         # Error handlers
│   ├── templates/      # Jinja2 templates
│   ├── static/         # CSS, JS, images
│   ├── models.py       # SQLAlchemy models
│   ├── config.py       # Configuration
│   └── cli.py          # Flask CLI commands
├── migrations/         # Database migrations
├── tests/              # Test suite
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker configuration
└── run.py              # Application entry point
```

---

## 🧪 Testing

```bash
# Run all tests
cd src
pytest

# Run with coverage
pytest --cov=apps --cov-report=html

# Run specific test file
pytest tests/test_routes.py -v
```

---

## 🚢 Deployment

### Deploy to Render

1. Connect your GitHub repository to Render
2. Create a new Web Service
3. Configure environment variables:
   - `DATABASE_URL` (Neon or Render PostgreSQL)
   - `SECRET_KEY` (auto-generated)
   - `FLASK_ENV=production`
4. Deploy!

Or use the `render.yaml` blueprint for Infrastructure as Code.

### CI/CD Pipeline

The project uses GitHub Actions for CI/CD:

- **On push to `develop`**: Run tests and linting
- **On push to `main`**: Run tests → Build → Deploy to Render

See `.github/workflows/deploy.yml` for configuration.

---

## 🛠️ CLI Commands

```bash
# Database migrations
flask db init          # Initialize migrations (first time)
flask db migrate -m "" # Create migration
flask db upgrade       # Apply migrations
flask db downgrade     # Rollback migration

# Setup commands
flask setup create-superadmin    # Create admin user
flask setup init-stock           # Initialize stock items
flask setup seed-reports --date  # Seed sample reports

# Development
flask run              # Start development server
flask shell            # Python shell with app context
```

---

## 🎨 Brand Guidelines

- **Primary Color (Logo Icon):** `#F58320` (Orange)
- **Secondary Color (Logo Text):** `#5E72E4` (Blue)
- **Font:** System fonts (Inter, -apple-system)

---

## 📱 Features

- ✅ User authentication (phone number + password)
- ✅ Stock management
- ✅ Sales tracking
- ✅ Client management with geolocation
- ✅ Cash flow tracking
- ✅ Report generation
- ✅ Multi-user support
- ✅ Mobile responsive design

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/issue-XX`
3. Make your changes
4. Run tests: `pytest`
5. Commit: `git commit -m "feat: description"`
6. Push: `git push origin feature/issue-XX`
7. Create a Pull Request to `develop`

See [Git Workflow Guide](./docs/git-workflow-guide.md) for details.

---

## 📄 License

MIT License - see [LICENSE.md](LICENSE.md)

---

## 📞 Support

- **WhatsApp:** [Contact Support](https://wa.me/243XXXXXXXXX)
- **Email:** support@airtfast.com
- **Issues:** [GitHub Issues](https://github.com/your-username/airtfast/issues)
