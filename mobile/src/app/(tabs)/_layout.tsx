import { Tabs } from 'expo-router';

import { TabBar } from '@/components/tab-bar';

export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false }} tabBar={(props) => <TabBar {...props} />}>
      <Tabs.Screen name="index" options={{ title: 'Главная' }} />
      <Tabs.Screen name="servers" options={{ title: 'Серверы' }} />
      <Tabs.Screen name="proxy" options={{ title: 'Прокси' }} />
      <Tabs.Screen name="key" options={{ title: 'Ключ' }} />
      <Tabs.Screen name="profile" options={{ title: 'Профиль' }} />
    </Tabs>
  );
}
