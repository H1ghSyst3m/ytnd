import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { User, Lock, CheckCircle, AlertCircle } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Card } from './ui/card';
import { useToast } from './ui/toast';
import { useCsrfToken } from '../hooks/useCsrfToken';
import * as api from '../lib/api';

export default function ProfileView() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  // Fetch profile data
  const { data: profile, isLoading } = useQuery({
    queryKey: ['profile'],
    queryFn: api.getProfile,
  });

  // Fetch CSRF token using custom hook
  const { token: csrfToken } = useCsrfToken();

  // Set credentials mutation
  const setCredentialsMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.setCredentials(username, password, csrfToken),
    onSuccess: () => {
      showToast('Your credentials have been set successfully.', 'success');
      queryClient.invalidateQueries({ queryKey: ['profile'] });
      setCredentialsForm({ username: '', password: '', confirmPassword: '' });
    },
    onError: (error: Error) => {
      showToast(error.message, 'error');
    },
  });

  // Update password mutation
  const updatePasswordMutation = useMutation({
    mutationFn: ({ currentPassword, newPassword }: { currentPassword: string; newPassword: string }) =>
      api.updatePassword(currentPassword, newPassword, csrfToken),
    onSuccess: () => {
      showToast('Your password has been updated successfully.', 'success');
      setPasswordForm({ currentPassword: '', newPassword: '', confirmNewPassword: '' });
    },
    onError: (error: Error) => {
      showToast(error.message, 'error');
    },
  });

  // Form states
  const [credentialsForm, setCredentialsForm] = useState({
    username: '',
    password: '',
    confirmPassword: '',
  });

  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmNewPassword: '',
  });

  // Validation errors
  const [credentialsErrors, setCredentialsErrors] = useState<string[]>([]);
  const [passwordErrors, setPasswordErrors] = useState<string[]>([]);

  // Validate credentials form
  useEffect(() => {
    const errors: string[] = [];
    if (credentialsForm.username && credentialsForm.username.length < 3) {
      errors.push('Username must be at least 3 characters');
    }
    if (credentialsForm.password && credentialsForm.password.length < 8) {
      errors.push('Password must be at least 8 characters');
    }
    if (credentialsForm.password && credentialsForm.confirmPassword &&
        credentialsForm.password !== credentialsForm.confirmPassword) {
      errors.push('Passwords do not match');
    }
    setCredentialsErrors(errors);
  }, [credentialsForm]);

  // Validate password form
  useEffect(() => {
    const errors: string[] = [];
    if (passwordForm.newPassword && passwordForm.newPassword.length < 8) {
      errors.push('Password must be at least 8 characters');
    }
    if (passwordForm.newPassword && passwordForm.confirmNewPassword &&
        passwordForm.newPassword !== passwordForm.confirmNewPassword) {
      errors.push('Passwords do not match');
    }
    setPasswordErrors(errors);
  }, [passwordForm]);

  const handleSetCredentials = (e: React.FormEvent) => {
    e.preventDefault();
    if (credentialsErrors.length > 0) return;
    
    setCredentialsMutation.mutate({
      username: credentialsForm.username,
      password: credentialsForm.password,
    });
  };

  const handleUpdatePassword = (e: React.FormEvent) => {
    e.preventDefault();
    if (passwordErrors.length > 0) return;
    
    updatePasswordMutation.mutate({
      currentPassword: passwordForm.currentPassword,
      newPassword: passwordForm.newPassword,
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-muted-foreground">Loading profile...</div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3 }}
      className="space-y-6 max-w-2xl"
    >
      <div>
        <h2 className="text-3xl font-bold">Profile Settings</h2>
        <p className="text-muted-foreground mt-1">
          Manage your account credentials and security settings
        </p>
      </div>

      {/* Current Profile Info */}
      <Card className="p-6">
        <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <User className="h-5 w-5" />
          Account Information
        </h3>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">User ID:</span>
            <span className="font-mono">{profile?.uid}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Role:</span>
            <span className="capitalize">{profile?.role}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Username:</span>
            <span>{profile?.username || <span className="text-muted-foreground italic">Not set</span>}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-muted-foreground">Password:</span>
            {profile?.hasPassword ? (
              <span className="flex items-center gap-1 text-green-600 dark:text-green-400">
                <CheckCircle className="h-4 w-4" />
                Set
              </span>
            ) : (
              <span className="flex items-center gap-1 text-yellow-600 dark:text-yellow-400">
                <AlertCircle className="h-4 w-4" />
                Not set
              </span>
            )}
          </div>
        </div>
      </Card>

      {/* Set/Update Credentials */}
      {!profile?.hasPassword && (
        <Card className="p-6">
          <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <User className="h-5 w-5" />
            Set Login Credentials
          </h3>
          <p className="text-sm text-muted-foreground mb-4">
            Set a username and password to enable login without a Telegram token.
          </p>
          <form onSubmit={handleSetCredentials} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-username">
                Username
              </label>
              <Input
                id="new-username"
                type="text"
                placeholder="Choose a username"
                value={credentialsForm.username}
                onChange={(e) => setCredentialsForm({ ...credentialsForm, username: e.target.value })}
                required
                autoComplete="username"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-password">
                Password
              </label>
              <Input
                id="new-password"
                type="password"
                placeholder="Choose a password (min 8 characters)"
                value={credentialsForm.password}
                onChange={(e) => setCredentialsForm({ ...credentialsForm, password: e.target.value })}
                required
                autoComplete="new-password"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="confirm-password">
                Confirm Password
              </label>
              <Input
                id="confirm-password"
                type="password"
                placeholder="Confirm your password"
                value={credentialsForm.confirmPassword}
                onChange={(e) => setCredentialsForm({ ...credentialsForm, confirmPassword: e.target.value })}
                required
                autoComplete="new-password"
              />
            </div>

            {credentialsErrors.length > 0 && (
              <div className="bg-destructive/10 text-destructive text-sm p-3 rounded-md space-y-1">
                {credentialsErrors.map((error, idx) => (
                  <div key={idx}>• {error}</div>
                ))}
              </div>
            )}

            <Button
              type="submit"
              disabled={credentialsErrors.length > 0 || setCredentialsMutation.isPending}
            >
              {setCredentialsMutation.isPending ? 'Setting...' : 'Set Credentials'}
            </Button>
          </form>
        </Card>
      )}

      {/* Change Password */}
      {profile?.hasPassword && (
        <Card className="p-6">
          <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Lock className="h-5 w-5" />
            Change Password
          </h3>
          <form onSubmit={handleUpdatePassword} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="current-password">
                Current Password
              </label>
              <Input
                id="current-password"
                type="password"
                placeholder="Enter your current password"
                value={passwordForm.currentPassword}
                onChange={(e) => setPasswordForm({ ...passwordForm, currentPassword: e.target.value })}
                required
                autoComplete="current-password"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-password-change">
                New Password
              </label>
              <Input
                id="new-password-change"
                type="password"
                placeholder="Enter new password (min 8 characters)"
                value={passwordForm.newPassword}
                onChange={(e) => setPasswordForm({ ...passwordForm, newPassword: e.target.value })}
                required
                autoComplete="new-password"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="confirm-new-password">
                Confirm New Password
              </label>
              <Input
                id="confirm-new-password"
                type="password"
                placeholder="Confirm your new password"
                value={passwordForm.confirmNewPassword}
                onChange={(e) => setPasswordForm({ ...passwordForm, confirmNewPassword: e.target.value })}
                required
                autoComplete="new-password"
              />
            </div>

            {passwordErrors.length > 0 && (
              <div className="bg-destructive/10 text-destructive text-sm p-3 rounded-md space-y-1">
                {passwordErrors.map((error, idx) => (
                  <div key={idx}>• {error}</div>
                ))}
              </div>
            )}

            <Button
              type="submit"
              disabled={passwordErrors.length > 0 || updatePasswordMutation.isPending}
            >
              {updatePasswordMutation.isPending ? 'Updating...' : 'Update Password'}
            </Button>
          </form>
        </Card>
      )}
    </motion.div>
  );
}
