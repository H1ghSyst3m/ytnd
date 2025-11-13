# YTND Manager Frontend

Modern web interface for the YTND (YouTube Nightcore Downloader) bot.

## Tech Stack

- **Framework**: React 18 with Vite
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **Animations**: Framer Motion
- **State Management**: React Query (TanStack Query)
- **UI Components**: Radix UI primitives
- **Icons**: Lucide React

## Features

- 🎵 **Songs Management**: View, download, and manage downloaded songs
- 👥 **User Management**: Admin interface for managing bot users
- 📥 **Download Queue**: Add and manage YouTube URLs for download
- 🌙 **Dark Mode**: Toggle between light and dark themes
- 📱 **Responsive**: Works on desktop and mobile devices
- ✨ **Smooth Animations**: Powered by Framer Motion

## Development

### Prerequisites

- Node.js 18+ and npm
- Backend server running (ytnd-bot Python application)

### Setup

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

### Environment

The frontend connects to the backend API at the same origin by default. If running in development with a separate backend, you may need to configure CORS on the backend.

## Building for Production

```bash
npm run build
```

This creates a `dist` folder with the production-ready static files. The backend (manager_server.py) serves these files automatically from the `dist` directory.

## API Integration

The frontend communicates with the following backend endpoints:

### Authentication
- `GET /auth/start?token=<token>` - One-time authentication
- `GET /auth/logout` - Logout

### Songs
- `GET /api/songs?user_id=<id>` - Get user's songs
- `DELETE /api/songs` - Delete a song
- `POST /api/redownload` - Re-download a song

### Users (Admin only)
- `GET /api/users` - Get list of user IDs
- `GET /api/users/detailed` - Get users with roles
- `POST /api/users` - Create a new user
- `PUT /api/users/{user_id}` - Update user role
- `DELETE /api/users/{user_id}` - Delete a user

### Download Queue
- `GET /api/queue?user_id=<id>` - Get download queue
- `POST /api/queue?user_id=<id>` - Add URLs to queue
- `DELETE /api/queue?user_id=<id>` - Remove URLs or clear queue

## Project Structure

```
manager-frontend/
├── src/
│   ├── components/
│   │   └── ui/           # Reusable UI components
│   ├── lib/
│   │   ├── api.ts        # API client functions
│   │   └── utils.ts      # Utility functions
│   ├── App.tsx           # Main application component
│   ├── main.tsx          # Application entry point
│   └── index.css         # Global styles
├── public/               # Static assets
├── dist/                 # Production build output
└── package.json          # Dependencies and scripts
```

