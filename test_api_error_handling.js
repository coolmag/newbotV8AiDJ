import { fetchPlaylist, APIError, checkAPIHealth } from '../webapp/js/api.js';

// Mock global fetch
global.fetch = jest.fn();

describe('API Error Handling', () => {
  beforeEach(() => {
    fetch.mockClear();
  });

  describe('APIError Class', () => {
    test('should create APIError with correct properties', () => {
      const error = new APIError('Test error', 'network', { status: 500 });
      
      expect(error.name).toBe('APIError');
      expect(error.message).toBe('Test error');
      expect(error.type).toBe('network');
      expect(error.details).toEqual({ status: 500 });
      expect(error.timestamp).toBeDefined();
    });

    test('should create APIError from fetch error without response', () => {
      const fetchError = new TypeError('Failed to fetch');
      const apiError = APIError.fromFetchError(fetchError);
      
      expect(apiError.type).toBe('network');
      expect(apiError.getUserMessage()).toBe('Ошибка сети: проверьте подключение к интернету');
    });

    test('should create APIError from fetch error with 404 response', () => {
      const response = { status: 404 };
      const apiError = APIError.fromFetchError(new Error('Not Found'), response);
      
      expect(apiError.type).toBe('not_found');
      expect(apiError.getUserMessage()).toBe('По вашему запросу ничего не найдено');
    });

    test('should create APIError from fetch error with 429 response', () => {
      const response = { status: 429 };
      const apiError = APIError.fromFetchError(new Error('Rate Limited'), response);
      
      expect(apiError.type).toBe('rate_limit');
      expect(apiError.getUserMessage()).toBe('Слишком много запросов. Подождите 1 минуту.');
    });

    test('should create APIError from fetch error with 500 response', () => {
      const response = { status: 500 };
      const apiError = APIError.fromFetchError(new Error('Server Error'), response);
      
      expect(apiError.type).toBe('server');
      expect(apiError.getUserMessage()).toBe('Сервер временно недоступен. Попробуйте позже.');
    });

    test('getUserMessage should return appropriate message for each error type', () => {
      const errorTypes = {
        network: 'Ошибка сети: проверьте подключение к интернету',
        server: 'Сервер временно недоступен. Попробуйте позже.',
        not_found: 'По вашему запросу ничего не найдено',
        rate_limit: 'Слишком много запросов. Подождите 1 минуту.',
        unknown: 'Произошла техническая ошибка'
      };

      Object.entries(errorTypes).forEach(([type, expectedMessage]) => {
        const error = new APIError('Test', type);
        expect(error.getUserMessage()).toBe(expectedMessage);
      });
    });
  });

  describe('fetchPlaylist', () => {
    test('should return playlist on successful response', async () => {
      const mockPlaylist = [{ id: 1, title: 'Test', artist: 'Artist' }];
      
      fetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ playlist: mockPlaylist })
      });

      const result = await fetchPlaylist('test query');
      
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining('query=test%20query'));
      expect(result).toEqual(mockPlaylist);
    });

    test('should return empty array when playlist is null', async () => {
      fetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ playlist: null })
      });

      const result = await fetchPlaylist('test');
      expect(result).toEqual([]);
    });

    test('should throw APIError on 404 response', async () => {
      fetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: 'Not Found'
      });

      await expect(fetchPlaylist('test')).rejects.toThrow(APIError);
      await expect(fetchPlaylist('test')).rejects.toMatchObject({
        type: 'not_found'
      });
    });

    test('should throw APIError on network failure', async () => {
      const networkError = new TypeError('Failed to fetch');
      fetch.mockRejectedValueOnce(networkError);

      await expect(fetchPlaylist('test')).rejects.toThrow(APIError);
      await expect(fetchPlaylist('test')).rejects.toMatchObject({
        type: 'network'
      });
    });

    test('should throw APIError on server error (500)', async () => {
      fetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error'
      });

      await expect(fetchPlaylist('test')).rejects.toThrow(APIError);
      await expect(fetchPlaylist('test')).rejects.toMatchObject({
        type: 'server'
      });
    });

    test('should throw APIError on rate limit (429)', async () => {
      fetch.mockResolvedValueOnce({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests'
      });

      await expect(fetchPlaylist('test')).rejects.toThrow(APIError);
      await expect(fetchPlaylist('test')).rejects.toMatchObject({
        type: 'rate_limit'
      });
    });
  });

  describe('checkAPIHealth', () => {
    test('should return health status on successful check', async () => {
      fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK'
      });

      const result = await checkAPIHealth();
      
      expect(result).toEqual({
        ok: true,
        status: 200,
        statusText: 'OK'
      });
    });

    test('should return error on network failure', async () => {
      const networkError = new TypeError('Failed to fetch');
      fetch.mockRejectedValueOnce(networkError);

      const result = await checkAPIHealth();
      
      expect(result.ok).toBe(false);
      expect(result.error).toBeInstanceOf(APIError);
      expect(result.error.type).toBe('network');
    });
  });
});