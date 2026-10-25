import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { View, useColorScheme } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useAppStore } from '@/store/app';
import { useTheme } from '@/theme';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 45_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export default function RootLayout() {
  const theme = useTheme();
  const scheme = useColorScheme();
  const hydrate = useAppStore((state) => state.hydrate);
  useEffect(() => {
    void hydrate();
  }, [hydrate]);
  const navigationTheme = {
    ...(scheme === 'light' ? DefaultTheme : DarkTheme),
    colors: {
      ...(scheme === 'light' ? DefaultTheme : DarkTheme).colors,
      background: theme.bg,
      card: theme.bg,
      text: theme.text,
      border: theme.line,
      primary: theme.accent,
    },
  };
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider value={navigationTheme}>
          <View style={{ flex: 1, backgroundColor: theme.bg }}>
            <StatusBar style={scheme === 'light' ? 'dark' : 'light'} />
            <Stack
              screenOptions={{
                headerShown: false,
                contentStyle: { backgroundColor: theme.bg },
                animation: 'fade',
              }}>
              <Stack.Screen name="(tabs)" />
              <Stack.Screen name="onboarding" options={{ presentation: 'fullScreenModal' }} />
            </Stack>
          </View>
        </ThemeProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
