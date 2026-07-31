# solver.py
import re
import logging

logger = logging.getLogger("XoS-Solver")

def solve_puzzle(question_text: str) -> str:
    """
    Ekstrak operasi matematika sederhana dari string pertanyaan
    seperti '12 + 7 = ?' dan mereturn hasilnya sebagai string.
    """
    logger.info(f"Solving puzzle for: {question_text}")
    # Regex sederhana untuk menangkap angka1, operator, angka2
    match = re.search(r'(\d+)\s*([\+\-\*])\s*(\d+)', question_text)
    if not match:
        logger.warning("Tidak dapat mengekstrak pola puzzle dari teks.")
        return "0"
        
    num1 = int(match.group(1))
    op = match.group(2)
    num2 = int(match.group(3))
    
    if op == '+':
        ans = num1 + num2
    elif op == '-':
        ans = num1 - num2
    elif op == '*':
        ans = num1 * num2
    else:
        ans = 0
        
    return str(ans)
