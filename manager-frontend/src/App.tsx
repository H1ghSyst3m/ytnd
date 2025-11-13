import { useState, useEffect } from 'react';
import { Routes, Route, Link, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { Menu, X, Music, Users, Download, LogOut, ScrollText, LayoutDashboard, UserCircle } from 'lucide-react';
import { ToastProvider } from './components/ui/toast';
import { Button, buttonVariants } from './components/ui/button';
import { Switch } from './components/ui/switch';
import { cn } from './lib/utils';
import DashboardView from './components/DashboardView';
import SongsView from './components/SongsView';
import UsersView from './components/UsersView';
import QueueView from './components/QueueView';
import LogView from './components/LogView';
import LoginView from './components/LoginView';
import ProfileView from './components/ProfileView';
import * as api from './lib/api';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MainApp />
      </ToastProvider>
    </QueryClientProvider>
  );
}

function MainApp() {
  const location = useLocation();
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('darkMode');
    return saved === 'true';
  });
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    // Default sidebar to open on desktop, closed on mobile
    return window.innerWidth >= 768;
  });
  const [selectedUser, setSelectedUser] = useState<string>('');
  const [isAdmin, setIsAdmin] = useState(false);

  // Check authentication status
  const { data: authData, isLoading: authLoading } = useQuery({
    queryKey: ['auth'],
    queryFn: api.checkAuth,
    retry: 1,
  });

  const isAuthenticated = authData?.authorized ?? false;

  const { data: users } = useQuery({
    queryKey: ['users'],
    queryFn: api.getUsers,
  });

  useEffect(() => {
    if (users && users.length > 0 && !selectedUser) {
      setSelectedUser(users[0]);
    }
  }, [users, selectedUser]);

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    localStorage.setItem('darkMode', String(darkMode));
  }, [darkMode]);

  // Check if user is admin
  useEffect(() => {
    api.getUsersDetailed()
      .then(() => setIsAdmin(true))
      .catch(() => setIsAdmin(false));
  }, []);

  const handleLogout = () => {
    api.logout();
  };

  // Show login view if not authenticated
  if (authLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background text-foreground">
        <div className="text-muted-foreground">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginView />;
  }

  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* Sidebar - overlays on mobile, static on desktop */}
      <AnimatePresence>
        {sidebarOpen && (
          <>
            {/* Mobile Overlay */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-0 bg-black/50 z-40 md:hidden"
              onClick={() => setSidebarOpen(false)}
            />
            
            <motion.aside
              initial={{ x: -256, width: 0, opacity: 0 }}
              animate={{ x: 0, width: 256, opacity: 1 }}
              exit={{ x: -256, width: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: 'easeInOut' }}
              className="fixed md:relative top-0 left-0 h-full bg-card border-r border-border flex flex-col overflow-hidden z-50"
            >
              <div className="p-4 sm:p-6 border-b border-border">
                <h1 className="text-xl sm:text-2xl font-bold">YTND Manager</h1>
              </div>
              
              <nav className="flex-1 p-3 sm:p-4 space-y-2 overflow-y-auto">
                <Link 
                  to="/" 
                  onClick={() => setSidebarOpen(false)}
                  className={cn(
                    buttonVariants({ 
                      variant: location.pathname === '/' ? 'default' : 'ghost',
                      className: "w-full justify-start"
                    })
                  )}
                >
                  <LayoutDashboard className="mr-2 h-4 w-4" />
                  Dashboard
                </Link>

                <Link 
                  to="/songs" 
                  onClick={() => setSidebarOpen(false)}
                  className={cn(
                    buttonVariants({ 
                      variant: location.pathname === '/songs' ? 'default' : 'ghost',
                      className: "w-full justify-start"
                    })
                  )}
                >
                  <Music className="mr-2 h-4 w-4" />
                  Songs
                </Link>
                
                <Link 
                  to="/queue" 
                  onClick={() => setSidebarOpen(false)}
                  className={cn(
                    buttonVariants({ 
                      variant: location.pathname === '/queue' ? 'default' : 'ghost',
                      className: "w-full justify-start"
                    })
                  )}
                >
                  <Download className="mr-2 h-4 w-4" />
                  Download Queue
                </Link>

                {isAdmin && (
                  <>
                    <Link 
                      to="/users" 
                      onClick={() => setSidebarOpen(false)}
                      className={cn(
                        buttonVariants({ 
                          variant: location.pathname === '/users' ? 'default' : 'ghost',
                          className: "w-full justify-start"
                        })
                      )}
                    >
                      <Users className="mr-2 h-4 w-4" />
                      User Management
                    </Link>
                    <Link 
                      to="/logs" 
                      onClick={() => setSidebarOpen(false)}
                      className={cn(
                        buttonVariants({ 
                          variant: location.pathname === '/logs' ? 'default' : 'ghost',
                          className: "w-full justify-start"
                        })
                      )}
                    >
                      <ScrollText className="mr-2 h-4 w-4" />
                      Log Viewer
                    </Link>
                  </>
                )}
                
                <Link 
                  to="/profile" 
                  onClick={() => setSidebarOpen(false)}
                  className={cn(
                    buttonVariants({ 
                      variant: location.pathname === '/profile' ? 'default' : 'ghost',
                      className: "w-full justify-start"
                    })
                  )}
                >
                  <UserCircle className="mr-2 h-4 w-4" />
                  Profile
                </Link>
                
              </nav>
              
              <div className="p-3 sm:p-4 border-t border-border space-y-3 sm:space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm">Dark Mode</span>
                  <Switch checked={darkMode} onCheckedChange={setDarkMode} />
                </div>
                <Button
                  variant="ghost"
                  className="w-full justify-start text-destructive"
                  onClick={handleLogout}
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  Logout
                </Button>
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-card border-b border-border p-3 sm:p-4 flex items-center justify-between gap-2">
          <Button 
            variant="ghost" 
            size="icon" 
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="flex-shrink-0"
          >
            {sidebarOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
          
          {isAdmin && users && users.length > 1 && location.pathname !== '/users' && location.pathname !== '/logs' && location.pathname !== '/' && location.pathname !== '/profile' && (
            <select
              className="bg-background border border-input rounded-md px-2 sm:px-3 py-2 text-sm min-w-0 flex-1 sm:flex-initial max-w-xs"
              value={selectedUser}
              onChange={(e) => setSelectedUser(e.target.value)}
            >
              {users.map((user) => (
                <option key={user} value={user}>{user}</option>
              ))}
            </select>
          )}
        </header>

        <main className="flex-1 overflow-auto p-4 sm:p-6">
          <Routes>
            <Route path="/" element={<DashboardView />} />
            <Route path="/songs" element={selectedUser ? <SongsView userId={selectedUser} /> : null} />
            <Route path="/queue" element={selectedUser ? <QueueView userId={selectedUser} /> : null} />
            {isAdmin && (
              <>
                <Route path="/users" element={<UsersView />} />
                <Route path="/logs" element={<LogView />} />
              </>
            )}
            <Route path="/profile" element={<ProfileView />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default App;