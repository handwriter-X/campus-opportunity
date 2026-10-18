import { View, Text } from '@tarojs/components'

/** 胶囊标签：固定高度，文字严格居中 */
export default function Pill({
  text,
  className = '',
  height = 36,
  fontSize = 20,
  paddingX = 16,
}: {
  text: string
  className?: string
  height?: number
  fontSize?: number
  paddingX?: number
}) {
  return (
    <View
      className={className}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        height: `${height}rpx`,
        padding: `0 ${paddingX}rpx`,
        borderRadius: `${height / 2}rpx`,
      }}
    >
      <Text style={{ fontSize: `${fontSize}rpx`, lineHeight: `${height}rpx`, height: `${height}rpx` }}>
        {text}
      </Text>
    </View>
  )
}
