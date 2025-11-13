import { useQuery } from '@tanstack/react-query';
import * as api from '../lib/api';

/**
 * Custom hook to fetch and manage CSRF token
 * @returns An object containing the CSRF token, loading state, and error state
 */
export function useCsrfToken() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['csrf-token'],
    queryFn: api.getCsrfToken,
  });

  return {
    token: data || '',
    isLoading,
    error,
  };
}
