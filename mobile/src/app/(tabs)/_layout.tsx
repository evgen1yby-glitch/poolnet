import { Tabs } from 'expo-router';

import { TabBar } from '@/components/tab-bar';
import { useT } from '@/lib/use-t';

export default function TabsLayout() {
  const t = useT();
  return (
    <Tabs screenOptions={{ headerShown: false }} tabBar={(props) => <TabBar {...props} />}>
      <Tabs.Screen name="index" options={{ title: t('tabs.vpn') }} />
      <Tabs.Screen name="proxy" options={{ title: t('tabs.proxy') }} />
      <Tabs.Screen name="support" options={{ title: t('tabs.support') }} />
      <Tabs.Screen name="profile" options={{ title: t('tabs.profile') }} />
    </Tabs>
  );
}
