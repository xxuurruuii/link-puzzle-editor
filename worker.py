# worker.py
import solver

def solver_worker(mode, data, queue):
    """
    运行在独立进程中的求解任务
    :param mode: 'SOLVE' 或 'DEDUCT'
    :param data: 序列化后的盘面数据
    :param queue: 用于回传结果的通信队列
    """
    try:
        result = []
        if mode == "SOLVE":
            result = solver.solve(data)
        elif mode == "DEDUCT":
            result = solver.deduct(data)
        queue.put(result)
    except Exception as e:
        print(f"Worker Error: {e}")
        queue.put(None)