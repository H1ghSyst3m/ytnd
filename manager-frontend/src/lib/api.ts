// API client for YTND Manager

const API_BASE = '';

export interface Song {
  id?: string;
  title: string;
  artist: string;
  url?: string;
  date?: string;
  cover?: string;
  file_available?: boolean;
  filename?: string;
  cover_available?: boolean;
}

export interface User {
  id: string;
  role: 'admin' | 'user';
}

export interface Profile {
  uid: string;
  username?: string;
  hasPassword: boolean;
  role: 'admin' | 'user';
}

export interface LogEntry {
  ts: string;
  lvl: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG';
  msg: string;
  [key: string]: any;
}

export interface ApiResponse<T> {
  [key: string]: T;
}

export interface RecentSong {
  title: string;
  artist: string;
  date?: string;
  cover_available?: boolean;
  cover?: string;
  id?: string;
}

export interface SystemStatus {
  status: 'ok' | 'error' | 'present' | 'missing';
  version?: string;
  detail?: string;
  latest?: string;
  updateAvailable?: boolean;
}

export interface AdminData {
  totalUsers: number;
  ytDlpStatus: SystemStatus;
  ffmpegStatus: SystemStatus;
  cookiesStatus: SystemStatus;
  syncthingStatus: SystemStatus;
  logSummary: {
    error: number;
    warning: number;
  };
}

export interface DashboardData {
  userId: string;
  songCount: number;
  queueSize: number;
  recentSongs: RecentSong[];
  adminData?: AdminData;
}

// Auth
export async function checkAuth(): Promise<{ authorized: boolean }> {
  const res = await fetch(`${API_BASE}/api/ping`);
  return res.json();
}

export async function login(username: string, password: string): Promise<{ success: boolean; userId: string }> {
  const formData = new FormData();
  formData.append('username', username);
  formData.append('password', password);
  
  const res = await fetch(`${API_BASE}/api/login`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  });
  
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Login failed');
  }
  
  return res.json();
}

export async function logout() {
  window.location.href = '/auth/logout';
}

// Profile
export async function getProfile(): Promise<Profile> {
  const res = await fetch(`${API_BASE}/api/profile`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Failed to fetch profile');
  }
  return res.json();
}

export async function getCsrfToken(): Promise<string> {
  const res = await fetch(`${API_BASE}/api/csrf-token`, {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error('Failed to get CSRF token');
  }
  const data = await res.json();
  return data.csrfToken;
}

export async function setCredentials(username: string, password: string, csrfToken: string): Promise<void> {
  const formData = new FormData();
  formData.append('username', username);
  formData.append('password', password);
  formData.append('csrf_token', csrfToken);
  
  const res = await fetch(`${API_BASE}/api/profile/credentials`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  });
  
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Failed to set credentials');
  }
}

export async function updatePassword(currentPassword: string, newPassword: string, csrfToken: string): Promise<void> {
  const formData = new FormData();
  formData.append('current_password', currentPassword);
  formData.append('new_password', newPassword);
  formData.append('csrf_token', csrfToken);
  
  const res = await fetch(`${API_BASE}/api/profile/password`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  });
  
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Failed to update password');
  }
}

// Users
export async function getUsers(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/users`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to fetch users');
  const data = await res.json();
  return data.users;
}

export async function getUsersDetailed(): Promise<User[]> {
  const res = await fetch(`${API_BASE}/api/users/detailed`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to fetch detailed users');
  const data = await res.json();
  return data.users;
}

export async function createUser(userId: string, role: 'admin' | 'user'): Promise<void> {
  const res = await fetch(`${API_BASE}/api/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ id: userId, role }),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Failed to create user');
  }
}

export async function updateUser(userId: string, role: 'admin' | 'user'): Promise<void> {
  const res = await fetch(`${API_BASE}/api/users/${userId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ role }),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Failed to update user');
  }
}

export async function deleteUser(userId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/users/${userId}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Failed to delete user');
  }
}

// Songs
export async function getSongs(userId: string): Promise<Song[]> {
  const res = await fetch(`${API_BASE}/api/songs?user_id=${userId}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to fetch songs');
  const data = await res.json();
  return data.songs;
}

export async function deleteSong(userId: string, song: { id?: string; title?: string; artist?: string }): Promise<void> {
  const params = new URLSearchParams({ user_id: userId });
  if (song.id) params.append('id', song.id);
  if (song.title) params.append('title', song.title);
  if (song.artist) params.append('artist', song.artist);

  const res = await fetch(`${API_BASE}/api/songs?${params}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to delete song');
}

export async function redownloadSong(
  userId: string,
  song: { id?: string; url?: string; title?: string; artist?: string },
  force: boolean = false
): Promise<void> {
  const params = new URLSearchParams({ user_id: userId, force: String(force) });
  if (song.url) params.append('url', song.url);
  if (song.id) params.append('id', song.id);
  if (song.title) params.append('title', song.title);
  if (song.artist) params.append('artist', song.artist);

  const res = await fetch(`${API_BASE}/api/redownload?${params}`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to redownload song');
}

export function getCoverUrl(userId: string, song: Song): string | null {
  if (!song.cover_available) return null;
  if (song.cover) {
    return `${API_BASE}/api/cover?user_id=${userId}&filename=${song.cover}`;
  }
  if (song.id) {
    return `${API_BASE}/api/cover?user_id=${userId}&id=${song.id}`;
  }
  return null;
}

export function getDownloadUrl(userId: string, filename: string): string {
  return `${API_BASE}/api/download?user_id=${userId}&filename=${filename}`;
}

// Queue
export async function getQueue(userId: string): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/queue?user_id=${userId}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to fetch queue');
  const data = await res.json();
  return data.queue;
}

export async function addToQueue(userId: string, urls: string[]): Promise<void> {
  const res = await fetch(`${API_BASE}/api/queue?user_id=${userId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ urls }),
  });
  if (!res.ok) throw new Error('Failed to add to queue');
}

export async function removeFromQueue(userId: string, urls?: string[]): Promise<void> {
  const body = urls ? { urls } : null;
  const res = await fetch(`${API_BASE}/api/queue?user_id=${userId}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error('Failed to remove from queue');
}

export async function probeUrl(url: string): Promise<{ ok: boolean; reason: string }> {
  const res = await fetch(`${API_BASE}/api/probe?url=${encodeURIComponent(url)}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to probe URL');
  return res.json();
}

// Logs
export async function getLogs(): Promise<LogEntry[]> {
  const res = await fetch(`${API_BASE}/api/logs`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Failed to fetch logs');
  }
  const data = await res.json();
  return data.logs;
}

// Dashboard
export async function getDashboardData(): Promise<DashboardData> {
  const res = await fetch(`${API_BASE}/api/dashboard`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Failed to fetch dashboard data');
  }
  return res.json();
}