export type Segment = { id: string; time: string; title: string; summary: string; transcript: string };
export const segments: Segment[] = [
{id:'average',time:'12:30–13:10',title:'평균변화율',summary:'두 점 사이의 기울기를 구하는 방법을 설명했어요.',transcript:'함수 위에 서로 다른 두 점을 잡아볼게요. x가 a에서 a+h로 변할 때, y는 f(a)에서 f(a+h)로 변합니다. 이때 y의 변화량을 x의 변화량으로 나눈 값, 즉 [f(a+h)−f(a)]/h가 두 점을 잇는 직선의 기울기예요. 이것을 평균변화율이라고 합니다.'},
{id:'instant',time:'13:10–14:00',title:'순간변화율로 연결',summary:'두 점의 간격 h를 0에 가깝게 줄이는 과정을 설명했어요.',transcript:'그럼 두 점을 점점 가깝게 가져가면 어떻게 될까요? 가로 간격 h를 0에 가깝게 줄여봅시다. 두 점을 지나는 직선은 한 점에서의 접선에 가까워져요. 평균변화율의 극한이 존재하면, 그 값이 바로 x=a에서의 순간변화율, 미분계수입니다.'},
{id:'example',time:'14:00–14:45',title:'f(x) = x²에 적용하기',summary:'평균변화율을 정리한 뒤 극한을 구하면, x=a에서의 미분계수는 2a가 돼요.',transcript:'f(x)=x²를 대입해 볼게요. [(a+h)²−a²]/h에서 분자를 전개하면 2ah+h²입니다. h는 0이 아니므로 약분하면 2a+h가 됩니다. 이제 h가 0으로 가까워질 때의 극한을 구하면 2a가 남습니다.'}
];
