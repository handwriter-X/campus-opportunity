export default defineAppConfig({
  pages: ['pages/index/index', 'pages/team/index'],
  window: {
    navigationBarBackgroundColor: '#ffffff',
    navigationBarTitleText: '校园活动',
    navigationBarTextStyle: 'black',
    backgroundColor: '#F5F6F8',
  },
  tabBar: {
    color: '#9ca3af',
    selectedColor: '#3b82f6',
    backgroundColor: '#ffffff',
    borderStyle: 'black',
    list: [
      { pagePath: 'pages/index/index', text: '校园活动' },
      { pagePath: 'pages/team/index', text: '组队机会池' },
    ],
  },
})
