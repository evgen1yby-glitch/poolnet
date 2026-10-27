import { Ionicons } from '@expo/vector-icons';
import { useEffect, useId, useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, {
  Easing,
  cancelAnimation,
  useAnimatedProps,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';
import Svg, {
  Circle,
  Defs,
  Ellipse,
  G,
  Line,
  LinearGradient,
  RadialGradient,
  Stop,
} from 'react-native-svg';

import { useTheme } from '@/theme';

export type ConnectOrbPhase = 'idle' | 'connecting' | 'reconnecting' | 'connected' | 'error';

export type ConnectOrbProps = {
  phase: ConnectOrbPhase;
  label: string;
  hint: string;
  onPress: () => void;
  disabled?: boolean;
};

const BUTTON_SIZE = 206;
const PROGRESS_SIZE = 220;
const CANVAS_SIZE = 256;
const HALO_SIZE = 244;
const BURST_SIZE = 218;
const TICK_COUNT = 64;
const BUTTON_RADIUS = BUTTON_SIZE / 2;
const PROGRESS_RADIUS = 109;
const PROGRESS_CIRCUMFERENCE = 2 * Math.PI * PROGRESS_RADIUS;
const CANVAS_CENTER = CANVAS_SIZE / 2;
const SCAN_RADIUS = 126;
const SCAN_CIRCUMFERENCE = 2 * Math.PI * SCAN_RADIUS;
const SCAN_ARC_LENGTH = SCAN_CIRCUMFERENCE * 0.17;

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

function centerOffset(size: number) {
  return (CANVAS_SIZE - size) / 2;
}

export function ConnectOrb({ phase, label, hint, onPress, disabled = false }: ConnectOrbProps) {
  const theme = useTheme();
  const reduceMotion = useReducedMotion();
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const scanGradientId = `scan-${uid}`;
  const faceGradientId = `face-${uid}`;
  const sheenGradientId = `sheen-${uid}`;
  const haloGradientId = `halo-${uid}`;

  const connected = phase === 'connected';
  const busy = phase === 'connecting' || phase === 'reconnecting';
  const failed = phase === 'error';
  const isDisabled = disabled || busy;

  const scanDuration = busy ? 2500 : connected ? 6500 : failed ? 22000 : 16000;
  const progressTarget = connected ? 1 : busy ? 0.68 : failed ? 0.22 : 0;

  const tickColor = connected || busy ? theme.text : failed ? theme.muted : theme.dim;
  const tickMajorOpacity = connected ? 0.95 : busy ? 0.72 : failed ? 0.5 : 0.4;
  const tickMinorOpacity = connected ? 0.62 : busy ? 0.42 : failed ? 0.28 : 0.2;
  const scanColor = theme.dark ? '#F4F4F4' : '#242424';
  const scanOpacity = connected ? 0.86 : busy ? 0.8 : failed ? 0.4 : 0.28;
  const progressColor = connected || busy ? theme.text : failed ? theme.muted : theme.dim;
  const coreBackground = connected ? '#F8F8F8' : '#080808';
  const coreBorder = connected ? 'rgba(0,0,0,0.16)' : 'rgba(255,255,255,0.16)';
  const iconColor = connected ? '#080808' : busy ? '#C7C7C7' : failed ? '#B9B9B9' : '#F2F2F2';

  const scanRotation = useSharedValue(0);
  const haloProgress = useSharedValue(connected ? 0 : 1);
  const burstProgress = useSharedValue(1);
  const pressScale = useSharedValue(1);
  const ringProgress = useSharedValue(progressTarget);

  const ticks = useMemo(
    () =>
      Array.from({ length: TICK_COUNT }, (_, index) => {
        const angle = (index / TICK_COUNT) * Math.PI * 2 - Math.PI / 2;
        const major = index % 8 === 0;
        const innerRadius = major ? 110.5 : 114.5;
        return {
          index,
          major,
          x1: CANVAS_CENTER + Math.cos(angle) * innerRadius,
          y1: CANVAS_CENTER + Math.sin(angle) * innerRadius,
          x2: CANVAS_CENTER + Math.cos(angle) * 120,
          y2: CANVAS_CENTER + Math.sin(angle) * 120,
        };
      }),
    [],
  );

  useEffect(() => {
    cancelAnimation(scanRotation);
    if (reduceMotion) {
      scanRotation.set(0);
      return;
    }
    scanRotation.set(0);
    scanRotation.set(
      withRepeat(
        withTiming(1, { duration: scanDuration, easing: Easing.linear }),
        -1,
        false,
      ),
    );
    return () => cancelAnimation(scanRotation);
  }, [reduceMotion, scanDuration, scanRotation]);

  useEffect(() => {
    cancelAnimation(haloProgress);
    if (!connected || reduceMotion) {
      haloProgress.set(
        withTiming(connected ? 0 : 1, {
          duration: reduceMotion ? 0 : 320,
          easing: Easing.out(Easing.quad),
        }),
      );
      return;
    }
    haloProgress.set(0);
    haloProgress.set(
      withRepeat(
        withTiming(1, { duration: 2200, easing: Easing.out(Easing.quad) }),
        -1,
        false,
      ),
    );
    return () => cancelAnimation(haloProgress);
  }, [connected, haloProgress, reduceMotion]);

  useEffect(() => {
    if (reduceMotion) {
      ringProgress.set(progressTarget);
      return;
    }
    ringProgress.set(
      withTiming(progressTarget, {
        duration: 620,
        easing: Easing.out(Easing.cubic),
      }),
    );
  }, [progressTarget, reduceMotion, ringProgress]);

  const scanStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${scanRotation.value * 360}deg` }],
  }));

  const haloStyle = useAnimatedStyle(() => ({
    opacity: (1 - haloProgress.value) * 0.62,
    transform: [{ scale: 0.98 + haloProgress.value * 0.055 }],
  }));

  const burstStyle = useAnimatedStyle(() => ({
    opacity: (1 - burstProgress.value) * 0.58,
    transform: [{ scale: 0.92 + burstProgress.value * 0.2 }],
  }));

  const buttonStyle = useAnimatedStyle(() => ({
    transform: [{ scale: pressScale.value }],
  }));

  const progressStyle = useAnimatedProps(() => ({
    strokeDashoffset: PROGRESS_CIRCUMFERENCE * (1 - ringProgress.value),
  }));

  const handlePress = () => {
    if (isDisabled) return;
    if (!reduceMotion) {
      burstProgress.set(0);
      burstProgress.set(
        withTiming(1, {
          duration: 620,
          easing: Easing.out(Easing.cubic),
        }),
      );
    }
    onPress();
  };

  const handlePressIn = () => {
    if (isDisabled || reduceMotion) return;
    pressScale.set(
      withTiming(0.968, {
        duration: 110,
        easing: Easing.out(Easing.quad),
      }),
    );
  };

  const handlePressOut = () => {
    if (reduceMotion) {
      pressScale.set(1);
      return;
    }
    pressScale.set(
      withTiming(1, {
        duration: 220,
        easing: Easing.bezier(0.23, 1, 0.32, 1),
      }),
    );
  };

  return (
    <View style={styles.root}>
      <View style={styles.stage}>
        <View style={styles.canvas}>
          <Animated.View
            pointerEvents="none"
            style={[
              styles.haloLayer,
              { top: centerOffset(HALO_SIZE), left: centerOffset(HALO_SIZE) },
              haloStyle,
            ]}>
            <Svg width={HALO_SIZE} height={HALO_SIZE} viewBox={`0 0 ${HALO_SIZE} ${HALO_SIZE}`}>
              <Defs>
                <RadialGradient
                  id={haloGradientId}
                  cx="50%"
                  cy="50%"
                  r="50%"
                  fx="50%"
                  fy="50%">
                  <Stop offset="0" stopColor={theme.text} stopOpacity={0} />
                  <Stop offset="0.66" stopColor={theme.text} stopOpacity={0} />
                  <Stop offset="0.8" stopColor={theme.text} stopOpacity={0.2} />
                  <Stop offset="0.92" stopColor={theme.text} stopOpacity={0.06} />
                  <Stop offset="1" stopColor={theme.text} stopOpacity={0} />
                </RadialGradient>
              </Defs>
              <Circle
                cx={HALO_SIZE / 2}
                cy={HALO_SIZE / 2}
                r={HALO_SIZE / 2}
                fill={`url(#${haloGradientId})`}
              />
            </Svg>
          </Animated.View>

          <View pointerEvents="none" style={styles.tickLayer}>
            <Svg width={CANVAS_SIZE} height={CANVAS_SIZE} viewBox={`0 0 ${CANVAS_SIZE} ${CANVAS_SIZE}`}>
              <G stroke={tickColor} strokeLinecap="round">
                {ticks.map((tick) => (
                  <Line
                    key={tick.index}
                    x1={tick.x1}
                    y1={tick.y1}
                    x2={tick.x2}
                    y2={tick.y2}
                    strokeWidth={tick.major ? 1.1 : 0.65}
                    strokeOpacity={tick.major ? tickMajorOpacity : tickMinorOpacity}
                  />
                ))}
              </G>
            </Svg>
          </View>

          <Animated.View pointerEvents="none" style={[styles.scanLayer, scanStyle]}>
            <Svg width={CANVAS_SIZE} height={CANVAS_SIZE} viewBox={`0 0 ${CANVAS_SIZE} ${CANVAS_SIZE}`}>
              <Defs>
                <LinearGradient
                  id={scanGradientId}
                  x1="0"
                  y1="0"
                  x2={CANVAS_SIZE}
                  y2={CANVAS_SIZE}
                  gradientUnits="userSpaceOnUse">
                  <Stop offset="0" stopColor={scanColor} stopOpacity={0.04} />
                  <Stop offset="0.42" stopColor={scanColor} stopOpacity={0.12} />
                  <Stop offset="0.8" stopColor={scanColor} stopOpacity={0.72} />
                  <Stop offset="1" stopColor={scanColor} stopOpacity={1} />
                </LinearGradient>
              </Defs>
              <Circle
                cx={CANVAS_CENTER}
                cy={CANVAS_CENTER}
                r={SCAN_RADIUS}
                fill="none"
                stroke={`url(#${scanGradientId})`}
                strokeWidth={1.15}
                strokeLinecap="round"
                strokeDasharray={`${SCAN_ARC_LENGTH} ${SCAN_CIRCUMFERENCE}`}
                opacity={scanOpacity}
              />
              <Circle
                cx={CANVAS_CENTER}
                cy={CANVAS_CENTER}
                r={SCAN_RADIUS}
                fill="none"
                stroke={scanColor}
                strokeWidth={3}
                strokeLinecap="round"
                strokeDasharray={`${SCAN_ARC_LENGTH * 0.22} ${SCAN_CIRCUMFERENCE}`}
                opacity={scanOpacity * 0.07}
              />
            </Svg>
          </Animated.View>

          <View
            pointerEvents="none"
            style={[
              styles.progressLayer,
              { top: centerOffset(PROGRESS_SIZE), left: centerOffset(PROGRESS_SIZE) },
            ]}>
            <Svg width={PROGRESS_SIZE} height={PROGRESS_SIZE} viewBox={`0 0 ${PROGRESS_SIZE} ${PROGRESS_SIZE}`}>
              <G rotation={-90} origin={`${PROGRESS_SIZE / 2}, ${PROGRESS_SIZE / 2}`}>
                <Circle
                  cx={PROGRESS_SIZE / 2}
                  cy={PROGRESS_SIZE / 2}
                  r={PROGRESS_RADIUS}
                  fill="none"
                  stroke={theme.line}
                  strokeWidth={1}
                />
                <AnimatedCircle
                  cx={PROGRESS_SIZE / 2}
                  cy={PROGRESS_SIZE / 2}
                  r={PROGRESS_RADIUS}
                  fill="none"
                  stroke={progressColor}
                  strokeWidth={1.4}
                  strokeLinecap="round"
                  strokeDasharray={`${PROGRESS_CIRCUMFERENCE} ${PROGRESS_CIRCUMFERENCE}`}
                  strokeDashoffset={PROGRESS_CIRCUMFERENCE}
                  animatedProps={progressStyle}
                  opacity={connected ? 1 : busy ? 0.82 : failed ? 0.6 : 0}
                />
              </G>
            </Svg>
          </View>

          <Animated.View
            pointerEvents="none"
            style={[
              styles.burstLayer,
              { top: centerOffset(BURST_SIZE), left: centerOffset(BURST_SIZE) },
              { borderColor: theme.text },
              burstStyle,
            ]}
          />

          <Animated.View
            style={[
              styles.buttonWrap,
              {
                shadowColor: theme.dark ? '#FFFFFF' : '#000000',
                shadowOpacity: theme.dark ? (connected ? 0.2 : 0.12) : 0.18,
              },
              buttonStyle,
            ]}>
            <AnimatedPressable
              accessible
              accessibilityRole="button"
              accessibilityLabel={`${label}. ${hint}`}
              accessibilityHint={hint}
              accessibilityState={{ busy, disabled: isDisabled, selected: connected }}
              disabled={isDisabled}
              onPress={handlePress}
              onPressIn={handlePressIn}
              onPressOut={handlePressOut}
              style={[
                styles.button,
                { borderColor: connected ? 'rgba(255,255,255,0.28)' : 'rgba(255,255,255,0.14)' },
              ]}>
              <Svg
                pointerEvents="none"
                width="100%"
                height="100%"
                viewBox={`0 0 ${BUTTON_SIZE} ${BUTTON_SIZE}`}
                style={StyleSheet.absoluteFill}>
                <Defs>
                  <RadialGradient
                    id={faceGradientId}
                    cx="36%"
                    cy="24%"
                    r="82%"
                    fx="36%"
                    fy="24%">
                    <Stop offset="0" stopColor={theme.dark ? '#353535' : '#2C2C2C'} />
                    <Stop offset="0.46" stopColor={theme.dark ? '#171717' : '#141414'} />
                    <Stop offset="1" stopColor="#050505" />
                  </RadialGradient>
                  <LinearGradient id={sheenGradientId} x1="0" y1="0" x2="0" y2="1">
                    <Stop offset="0" stopColor="#FFFFFF" stopOpacity={0.16} />
                    <Stop offset="1" stopColor="#FFFFFF" stopOpacity={0} />
                  </LinearGradient>
                </Defs>
                <Circle
                  cx={BUTTON_SIZE / 2}
                  cy={BUTTON_SIZE / 2}
                  r={BUTTON_RADIUS - 0.5}
                  fill={`url(#${faceGradientId})`}
                />
                <Ellipse
                  cx={BUTTON_SIZE / 2 - 10}
                  cy={46}
                  rx={68}
                  ry={31}
                  fill={`url(#${sheenGradientId})`}
                />
                <Circle
                  cx={BUTTON_SIZE / 2}
                  cy={BUTTON_SIZE / 2}
                  r={78}
                  fill="none"
                  stroke="#FFFFFF"
                  strokeOpacity={0.055}
                  strokeWidth={1}
                />
              </Svg>

              <View
                style={[
                  styles.core,
                  {
                    backgroundColor: coreBackground,
                    borderColor: coreBorder,
                    shadowColor: connected ? '#FFFFFF' : '#000000',
                    shadowOpacity: connected ? 0.34 : 0.5,
                  },
                ]}>
                <Ionicons
                  name={connected ? 'shield-checkmark' : failed ? 'alert-circle-outline' : 'power'}
                  size={connected ? 46 : 42}
                  color={iconColor}
                />
              </View>
            </AnimatedPressable>
          </Animated.View>
        </View>
      </View>

      <View style={styles.caption}>
        <Text
          accessibilityLiveRegion="polite"
          numberOfLines={1}
          style={[styles.label, { color: theme.text }]}>
          {label}
        </Text>
        <Text numberOfLines={1} style={[styles.hint, { color: theme.muted }]}>
          {hint}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    width: '100%',
    maxWidth: 350,
    height: 322,
    alignSelf: 'center',
    alignItems: 'center',
  },
  stage: {
    width: '100%',
    height: 260,
    alignItems: 'center',
    justifyContent: 'center',
  },
  canvas: {
    width: CANVAS_SIZE,
    height: CANVAS_SIZE,
    alignItems: 'center',
    justifyContent: 'center',
  },
  haloLayer: {
    position: 'absolute',
    width: HALO_SIZE,
    height: HALO_SIZE,
  },
  tickLayer: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: CANVAS_SIZE,
    height: CANVAS_SIZE,
  },
  scanLayer: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: CANVAS_SIZE,
    height: CANVAS_SIZE,
  },
  progressLayer: {
    position: 'absolute',
    width: PROGRESS_SIZE,
    height: PROGRESS_SIZE,
  },
  burstLayer: {
    position: 'absolute',
    width: BURST_SIZE,
    height: BURST_SIZE,
    borderRadius: BURST_SIZE / 2,
    borderWidth: 1,
  },
  buttonWrap: {
    width: BUTTON_SIZE,
    height: BUTTON_SIZE,
    borderRadius: BUTTON_RADIUS,
    shadowOffset: { width: 0, height: 0 },
    shadowRadius: 32,
    elevation: 14,
  },
  button: {
    width: BUTTON_SIZE,
    height: BUTTON_SIZE,
    borderRadius: BUTTON_RADIUS,
    borderWidth: 1,
    backgroundColor: '#080808',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  core: {
    width: 96,
    height: 96,
    borderRadius: 48,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    shadowOffset: { width: 0, height: 7 },
    shadowRadius: 18,
    elevation: 8,
  },
  caption: {
    width: '100%',
    height: 62,
    paddingTop: 4,
    paddingHorizontal: 12,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  label: {
    maxWidth: 320,
    textAlign: 'center',
    fontSize: 16,
    lineHeight: 20,
    fontWeight: '600',
    letterSpacing: -0.2,
  },
  hint: {
    maxWidth: 320,
    textAlign: 'center',
    fontSize: 11.5,
    lineHeight: 15,
    fontWeight: '400',
    letterSpacing: 0.05,
  },
});
