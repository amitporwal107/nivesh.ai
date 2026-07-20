package ai.nivesh.app.ui.performance;

import ai.nivesh.app.data.repo.DashboardsRepository;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class PerformanceViewModel_Factory implements Factory<PerformanceViewModel> {
  private final Provider<DashboardsRepository> repoProvider;

  public PerformanceViewModel_Factory(Provider<DashboardsRepository> repoProvider) {
    this.repoProvider = repoProvider;
  }

  @Override
  public PerformanceViewModel get() {
    return newInstance(repoProvider.get());
  }

  public static PerformanceViewModel_Factory create(Provider<DashboardsRepository> repoProvider) {
    return new PerformanceViewModel_Factory(repoProvider);
  }

  public static PerformanceViewModel newInstance(DashboardsRepository repo) {
    return new PerformanceViewModel(repo);
  }
}
