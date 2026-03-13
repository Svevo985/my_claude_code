class Game:
    def __init__(self):
        self.board = [[' '] * 3 for _ in range(3)]
        self.player = 'X'

    def display(self):
        print('\n'.join([' | '.join(row) for row in self.board]))

    def is_valid_move(self, x, y):
        return 0 <= x < 3 and 0 <= y < 3 and self.board[x][y] == ' '

    def make_move(self, x, y):
        if not self.is_valid_move(x, y): 
            print('Invalid move')
            return False
        self.board[x][y] = self.player
        return True

    def switch_player(self):
        self.player = 'O' if self.player == 'X' else 'X'

    def run(self):
        while True:
            print('\nCurrent player:', self.player)
            self.display()
            try:
                move = input('Enter position (row,col): ').split(',')
                x, y = int(move[0]), int(move[1])
                if not self.make_move(x,y):
                    continue
                self.switch_player()
                break  # Exit loop after one move for demo purposes
            except Exception as e:
                print('Error:', str(e))

if __name__ == '__main__':
    game = Game()
    game.run()