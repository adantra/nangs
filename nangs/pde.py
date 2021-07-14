from fastprogress import master_bar, progress_bar
from .history import History
import torch
from .utils import *
import numpy as np
import matplotlib.pyplot as plt


def get_lr(optimizer):
    for param_group in optimizer.param_groups:
        return param_group['lr']


class PDE():

    def __init__(self, inputs, outputs):

        # check lists of unique strings, non-repeated
        if isinstance(inputs, str):
            inputs = tuple(inputs)
        if isinstance(outputs, str):
            outputs = tuple(outputs)

        checkIsListOfStr(inputs)
        checkIsListOfStr(outputs)
        checkUnique(inputs)
        checkUnique(outputs)
        checkNoRepeated(inputs, outputs)

        self.inputs = inputs
        self.outputs = outputs
        self.mesh = None
        self.bocos = []

    def set_mesh(self, mesh):
        assert mesh.vars == self.inputs, "your data does not match the PDE inputs"
        self.mesh = mesh

    def add_boco(self, boco):
        assert boco.name not in [
            boco.name for boco in self.bocos], f'Boco {boco.name} already exists, use another name'
        boco.validate(self.inputs, self.outputs)
        self.bocos.append(boco)

    def compile(self, model, optimizer, scheduler=None, criterion=None):
        self.model = model
        self.optimizer = optimizer
        self.criterion = criterion if criterion else torch.nn.MSELoss()
        self.scheduler = scheduler

    def computePDELoss(self, vars, grads):
        print("This function need to be overloaded !!!")

    def solve(self, epochs=50, batch_size=None, shuffle=True, graph=True):
        dataloaders = self.set_dataloaders(batch_size, shuffle)
        if graph:
            self.graph_fig, (self.graph_ax1, self.graph_ax2) = plt.subplots(
                1, 2, figsize=(15, 5))
            self.graph_out = display(self.graph_fig, display_id=True)
        # solve PDE
        history = History()
        mb = master_bar(range(1, epochs+1))
        for epoch in mb:
            history.add({'lr': get_lr(self.optimizer)})
            # iterate over the internal points in batches
            for batch in progress_bar(dataloaders['inner'], parent=mb):
                X = batch
                self.optimizer.zero_grad()
                # optimize for boundary points
                for boco in self.bocos:
                    for batch in dataloaders['bocos'][boco.name]:
                        loss = boco.computeLoss(
                            batch, self.model, self.criterion)
                        for name, l in loss.items():
                            l.backward()
                            history.add_step({name: l.item()})
                # optimize for internal points
                X.requires_grad = True
                p = self.model(X)
                loss = self.computePDELoss(X, p)
                assert isinstance(
                    loss, dict), "you should return a dict with the name of the equation and the corresponding loss"
                for name, l in loss.items():
                    l = self.criterion(l, torch.zeros(
                        l.shape).to(self.mesh.device))
                    l.backward(retain_graph=True)
                    history.add_step({name: l.item()})
                self.optimizer.step()
                mb.child.comment = str(history.average())
            history.step()
            mb.main_bar.comment = str(history)
            if graph:
                self.plot_history(history)
            # mb.write(f"Epoch {epoch}/{epochs} {history}")
            if self.scheduler:
                self.scheduler.step()
        if graph:
            plt.close()
        return history.history

    def plot_history(self, history):
        self.graph_ax1.clear()
        self.graph_ax2.clear()
        for name, metric in history.history.items():
            if name != 'lr':
                self.graph_ax1.plot(metric, label=name)
            else:
                self.graph_ax2.plot(metric, label=name)
        self.graph_ax1.legend(loc='upper right')
        self.graph_ax2.legend(loc='upper right')
        self.graph_ax1.grid(True)
        self.graph_ax2.grid(True)
        self.graph_ax1.set_yscale("log")
        self.graph_out.update(self.graph_fig)

    def set_dataloaders(self, batch_size, shuffle):
        dataloaders = {
            'inner': self.mesh.build_dataloader(batch_size, shuffle),
            'bocos': {}
        }
        for boco in self.bocos:
            dataloaders['bocos'][boco.name] = boco.build_dataloader(
                batch_size, shuffle)
        return dataloaders

    def computeGrads(self, outputs, inputs):
        grads, = torch.autograd.grad(outputs, inputs,
                                     grad_outputs=outputs.data.new(
                                         outputs.shape).fill_(1),
                                     create_graph=True, only_inputs=True)
        return grads

    def eval(self, mesh, batch_size=None):
        dataloader = mesh.build_dataloader(batch_size, shuffle=False)
        outputs = torch.tensor([]).to(mesh.device)
        self.model.eval()
        with torch.no_grad():
            for batch in dataloader:
                outputs = torch.cat([outputs, self.model(batch)])
        return outputs

    def eval_with_grad(self, mesh, batch_size=None):
        dataloader = mesh.build_dataloader(batch_size, shuffle=False)
        outputs = torch.tensor([]).to(mesh.device)
        self.model.eval()
        # with torch.no_grad():
        for batch in dataloader:
            batch.requires_grad = True
            outputs = self.model(batch)
            # for batch in dataloader:

            # outputs = self.model(batch)
            p = outputs
            X = batch
            X.requires_grad = True
            grad, = torch.autograd.grad(p, X,
                                        grad_outputs=p.data.new(p.shape).fill_(1),
                                        create_graph=True, only_inputs=True)
            loss = self.computePDELoss(X, p)
        return outputs, grad, loss['pde'].detach().cpu().numpy()
